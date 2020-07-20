#!/usr/bin/env python3
from panda import Panda, ffi, blocking
from panda.x86.helper import dump_regs, registers
from datetime import datetime, timedelta

from flask import Flask, request, render_template
import threading
from graphviz import Graph
import base64

# Start with a basic flask app webpage.
from flask_socketio import SocketIO, emit
from flask import Flask, render_template, url_for, copy_current_request_context
from random import random
from time import sleep
from threading import Thread, Event

app = Flask(__name__)
app.use_reloader = False
app.debug = False
app.config['SECRET_KEY'] = 'secret!'
app.config['DEBUG'] = True

#turn the flask app into a socketio app
socketio = SocketIO(app, async_mode=None, logger=True, engineio_logger=True, debug=False, use_reloader=False)

panda = Panda("x86_64", mem="1G",qcow="/home/luke/.panda/bionic-server-cloudimg-amd64-noaslr-nokaslr.qcow2",
            expect_prompt=rb"root@ubuntu:.*",
            extra_args=["-nographic",                           
            "-net", "nic,netdev=net0",
            "-netdev", "user,id=net0,",  
            ])

panda.set_os_name("linux-64-ubuntu:4.15.0-72-generic-noaslr-nokaslr")

connected_count = 0

class Process(object):
    def __init__(self, proc_object):
        self.taskd = proc_object.taskd
        self.asid = proc_object.asid
        self.pid = proc_object.pid
        self.ppid = proc_object.ppid
        self.start_time = proc_object.create_time
        try:
            self.name = ffi.string(proc_object.name).decode()
        except:
            self.name = "?"
        self.pages = proc_object.pages
        self.children = set()
        self.parent = None
        self.tmp_parent_pid = None

    def set_parent(self, parent):
        self.parent = parent

    def add_child(self, other):
        if other != self:
            self.children.add(other)
        else:
            print(f"{self.name} is the same as {other.name}")
    
    def __hash__(self):
        return hash((self.taskd, self.asid, self.pid, self.ppid, self.name, self.pages, self.start_time))

    def __eq__(self, other):
        if not isinstance(other, Process):
            return False
        return self.taskd == other.taskd and self.asid == other.asid and self.pid == other.pid and self.ppid == other.ppid and self.name == other.name and self.pages == other.pages and self.start_time == other.start_time

processes = set()
time_stop = 1000

time_start = datetime.now()

'''
There isn't a direct mapping between pid and processes. This is because pids are
recycled. We look through all processes and find the most recently started
process that matches our PID.
'''
def get_pid_object(pid):
    best = None
    for process in processes:
        if process.pid == pid:
            if not best:
                best = process
            else:
                best = process if best.start_time < process.start_time else best
    return best

nodes_to_add = {} 
'''
So we want to resolve not a PID number, but an object. For that reaon we want
to wait and resolve it once the object is in our processes set. Otherwise we
keep things in the "tmp_parent_pid" variable. This lets us know that we don't
have a proper parent and need to work on that.
'''
def try_resolve_parent(proc_obj):
    global nodes_to_add
    parent_pid = proc_obj.ppid
    parent = get_pid_object(parent_pid)
    if parent and not proc_obj.parent:
        proc_obj.set_parent(parent)
        parent.add_child(proc_obj)
        proc_obj.tmp_parent_pid = None
        print(f"new pair {parent.name} {proc_obj.name}")
        for nodes in nodes_to_add:
            nodes_to_add[nodes].append({'pproc':f"{parent.name}_{hex(parent.start_time)[2:]}", 'child':f"{proc_obj.name}_{hex(proc_obj.start_time)[2:]}"})
        if not nodes_to_add:
            print("no nodes_to_add")
#            socketio.emit('my response',{'pproc':parent.name,'child': proc_obj.name}, callback=messageReceived, broadcast=True)
        #nodes_to_add.append({'pproc':parent.name,'child': proc_obj.name})
    else:
        proc_obj.tmp_parent_pid = parent_pid


def is_kernel_sub(proc):
    if "kthreadd" in proc.name:
        return True
    parent = proc.parent
    if parent and not proc == parent:
        return is_kernel_sub(parent)
    return False

'''
On asid change we iterate over the entire process list. If unseen it could be
that the process changed names or that the process is actually new. If its new
we try to resolve its parent and add it to the parent process. If its just a 
process name change we remove the old and do the same process.

Next, we cycle back through processes which failed to resolve the parent process
and rematch them with try_resolve_parent.

We also use this as a convenient place to end the recording at a certain amount
of time.
'''
@panda.cb_asid_changed
def asid_changed(env, old_asid, new_asid):
    for process in panda.get_processes(env):
        proc_obj = Process(process)
        if proc_obj not in processes:
            # is this a name change?
            # assumption: same start time -> same task -> switch them out
            same_obj = None
            for p_compare in processes:
                if p_compare.start_time == proc_obj.start_time:
                    if not is_kernel_sub(proc_obj) and not is_kernel_sub(p_compare):
                        same_obj = p_compare
                        break
            if same_obj:
                print(f"{same_obj.name} is the same as {proc_obj.name}")
#                import ipdb
#                ipdb.set_trace()
                processes.remove(same_obj)
                if same_obj.parent:
                    same_obj.parent.children.remove(same_obj)
            # new process
            processes.add(proc_obj)
            try_resolve_parent(proc_obj)

    # if the parent process isn't in our list before we get there
    # then we go through and add it here
    for process in processes:
        if process.tmp_parent_pid:
            print(f"secondary resolve for {process.name}")
            try_resolve_parent(process)

    if datetime.now() - time_start > timedelta(seconds=time_stop):
        panda.end_analysis()
    return 0

# run some commands
@blocking
def run_cmd():
    panda.revert_sync("root")
    print(panda.run_serial_cmd("uname -a"))
    print(panda.run_serial_cmd("ls -la"))
    print(panda.run_serial_cmd("whoami"))
    print(panda.run_serial_cmd("date"))
    print(panda.run_serial_cmd("sleep 10"))
    print(panda.run_serial_cmd("uname -a | cat | cat | cat | cat | tee /asdf"))
    print(panda.run_serial_cmd("watch watch watch watch watch watch date"))
	

@app.route("/")
def graph():
    g = Graph('unix', filename='process',engine='dot')
#                node_attr={'color':'lightblue2',  'arrowhead': 'vee'})
    def traverse_internal(node):
        for child in node.children:
            g.edge(f"{node.name}_{hex(node.start_time)[2:]}".replace(":",""), f"{child.name}_{hex(child.start_time)[2:]}".replace(":",""))
            traverse_internal(child)
    init = get_pid_object(0)
    traverse_internal(init)
#    g.render(format='png', filename='process.png',view=False)
#    chart_output = g.pipe(format='png')
#    chart_output = base64.b64encode(chart_output).decode('utf-8')
    return render_template('svgtest.html', chart_output=g.source)



#random number Generator Thread
thread = Thread()
thread_stop_event = Event()

def emitEvents():
    """
    Generate a random number every 1 second and emit to a socketio instance (broadcast)
    Ideally to be run in a separate thread?
    """
    import random
    import string
    global nodes_to_add
    def get_random_string(length):
        letters = string.ascii_lowercase
        result_str = ''.join(random.choice(letters) for i in range(length))
        return result_str
    #infinite loop of magical random numbers
    my_string = get_random_string(8)
    nodes_to_add[my_string] = []
    my_nodes_to_add = nodes_to_add[my_string]
    print(f"Making random numbers {my_string}")
    while not thread_stop_event.isSet():
        if my_nodes_to_add:
            p = my_nodes_to_add.pop(0)
            print(f"emitting newprocess {p}")
            socketio.emit('newprocess', p, namespace='/test')
        else:
            print(f"No nodes to add {len(my_nodes_to_add)}")
        socketio.sleep(1)

@socketio.on('connect', namespace='/test')
def test_connect():
    # need visibility of the global thread object
    global thread
    print('Client connected')

    #Start the random number generator thread only if the thread has not been started before.
    if not thread.isAlive():
        print("Starting Thread")
        thread = socketio.start_background_task(emitEvents)

@socketio.on('disconnect', namespace='/test')
def test_disconnect():
    print('Client disconnected')

def start_flask():
    socketio.run(app,host='0.0.0.0',port=8888, debug=False, use_reloader=False)

x = threading.Thread(target=start_flask)
x.start()

panda.queue_async(run_cmd)
panda.run()


g = Graph('unix', filename='process',engine='dot',
            node_attr={'color':'lightblue2', 'style':'filled', 'arrowhead': 'vee'})

def traverse(node, parentstr):
    if parentstr:
        parentstr += f"-> {node.name}_{hex(node.start_time)[2:]} "
    else:
        parentstr = f"{node.name}_{hex(node.start_time)[2:]} "
    print(parentstr)
    for child in node.children:
        g.edge(f"{node.name}_{hex(node.start_time)[2:]}".replace(":",""), f"{child.name}_{hex(child.start_time)[2:]}".replace(":",""))
        traverse(child, parentstr)

print("PROCESS LIST")
init = get_pid_object(0)
traverse(init,"")
g.render(format='png', filename='process.png',view=False)
x.join()
