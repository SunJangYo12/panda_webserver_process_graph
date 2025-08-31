from pandare import Panda, blocking
from flask import Flask, request, render_template
from flask_socketio import SocketIO, emit

import threading
from threading import Thread, Event

from graphviz import Graph
from string import ascii_lowercase
from random import choice

thread = Thread()
thread_stop_event = Event()


#turn the flask app into a socketio app
app = Flask(__name__)
app.use_reloader = False
app.debug = False
app.config['SECRET_KEY'] = 'secret!'
app.config['DEBUG'] = True

socketio = SocketIO(app, async_mode=None, logger=True, engineio_logger=True, debug=False, use_reloader=False)



# Panda object sets up virtual machine options
#-nographic is analagous to -display none (text console)
panda = Panda("x86_64", mem="1G",expect_prompt=rb"root@ubuntu:.*",
	qcow="bak/bionic-server-cloudimg-amd64-noaslr-nokaslr.qcow2",
	extra_args=["-nographic"])
# set our OS name for OSI
panda.set_os_name("linux-64-ubuntu:4.15.0-72-generic-noaslr-nokaslr")



class Process(object):
    def __init__(self, proc_object):
        self.pid = proc_object.pid
        self.ppid = proc_object.ppid
        self.start_time = proc_object.create_time
        self.name = panda.ffi.string(proc_object.name).decode()
        self.children = set()
        self.parent = None

    @property
    def depth(self):
        if self.parent is self or not self.parent:
            return 1
        return 1 + self.parent.depth

    def add_child(self, other):
	    # avoid self loops
        if not other is self:
            self.children.add(other)

    def is_kernel_task(self):
        if "kthreadd" in self.name:
            return True
        if self.parent and not self.parent is self:
            return self.parent.is_kernel_task()
        return False

    def __hash__(self):
        return hash((self.pid, self.ppid, self.name, self.start_time))

    def __eq__(self, other):
        if not isinstance(other, Process):
            return False
        # start_times can collide with kernel tasks
        if not self.is_kernel_task():
            return self.start_time == other.start_time
        return self.pid == other.pid

    def __str__(self):
	    # replace ":" with "" because graphviz messes ":" up
        return f"{self.name}_{hex(self.start_time)[2:]}".replace(":","")



# our list of processes
processes = set()
nodes_to_add = {}
nodes_to_remove = {}

@panda.cb_asid_changed
def asid_changed(env, old_asid, new_asid):
    global processes

    # get all unique processes
    new_processes = set()

    # make a mapping from PID -> process
    pid_mapping = {}

    for process in panda.get_processes(env):
        #print(f"MYDEBUG: {panda.ffi.string(process.name)}")

        proc_obj = Process(process)
        new_processes.add(proc_obj)
        pid_mapping[proc_obj.pid] = proc_obj

    # iterate over our processes again, from low to high PID,
    # and add the parent <-> child relation
    processes_to_consider = list(new_processes)
    processes_to_consider.sort(key=lambda x: x.pid)

    for process in processes_to_consider:
        parent = pid_mapping[process.ppid]
        process.parent = parent
        parent.add_child(process)

    # convert back to a set
    proc_new = set(processes_to_consider)

    # python lets us do set difference with subtraction
    # these are the changes in the process
    new_processes = proc_new - processes
    dead_processes = processes - proc_new

    # set the new process mapping
    processes = proc_new

    # add started processes for each connection
    for nodes in nodes_to_add:
        for node in new_processes:
            nodes_to_add[nodes].add(node)
    # add exited processes for each connection
    for nodes in nodes_to_remove:
        for node in dead_processes:
            nodes_to_remove[nodes].add(node)
    return 0


@blocking
def run_commands():
     panda.revert_sync("myroot")
     while True:
        print("zzzzzz")
        print(panda.run_serial_cmd("sleep 10"))
        print(panda.run_serial_cmd("uname -a"))
        print(panda.run_serial_cmd("ls -la"))
        print(panda.run_serial_cmd("whoami"))
        print(panda.run_serial_cmd("date"))
        print(panda.run_serial_cmd("uname -a | cat | cat | cat | cat | tee /asdf"))
        print(panda.run_serial_cmd("time time time time time whoami"))
        print(panda.run_serial_cmd("sleep 10"))
        print(panda.run_serial_cmd("watch watch watch watch watch watch date &"))







def get_random_string(length):
    letters = ascii_lowercase
    return ''.join(choice(letters) for i in range(length))

def emitEvents():
    global nodes_to_add
    my_string = get_random_string(8)
    nodes_to_add[my_string] = set()
    nodes_to_remove[my_string] = set()
    my_nodes_to_add = nodes_to_add[my_string]
    my_nodes_to_remove = nodes_to_remove[my_string]

    while not thread_stop_event.isSet():
        # find our intersection of events. remove them
        snta = set(my_nodes_to_add)
        sntr = set(my_nodes_to_remove)
        common = snta.intersection(sntr)

        for i in list(common):
            my_nodes_to_add.remove(i)
            my_nodes_to_remove.remove(i)

        # sort nodes to add by depth
        nodes_to_add_sorted = list(my_nodes_to_add)
        sorted(nodes_to_add_sorted, key=lambda x: x.depth)

        if my_nodes_to_add:
            p = nodes_to_add_sorted[0]
            my_nodes_to_add.remove(p)

            print(f"emitting newprocess {p}")
            parent = p.parent
            #socketio.emit('newprocess', 'operation': 'add', pproc': str(parent), child': str(p)}, namespace='/test')
            socketio.emit('newprocess', {'operation': 'add', 'pproc': str(parent), 'child': str(p)}, namespace='/test')

        nodes_to_remove_sorted = list(my_nodes_to_remove)
        sorted(nodes_to_remove_sorted, key=lambda x: -x.depth)

        if my_nodes_to_remove:
            p = nodes_to_remove_sorted[0]
            my_nodes_to_remove.remove(p)

            print(f"emitting remove {p}")
            parent = p.parent
            #socketio.emit('newprocess', operation': 'remove', pproc': str(parent), child': str(p)}, namespace='/test')
            socketio.emit('newprocess', {'operation': 'remove', 'pproc': str(parent), 'child': str(p)}, namespace='/test')

        socketio.sleep(0.1)



@socketio.on('connect', namespace='/test')
def test_connect():
    # need visibility of the global thread object
    global thread
    print('Client connected')
    if not thread.is_alive():
        print("Starting Thread")
        thread = socketio.start_background_task(emitEvents)

@socketio.on('disconnect', namespace='/test')
def test_disconnect():
    print('Client disconnected')


def get_pid_object(pid):
    best = None
    for process in processes:
        if process.pid == pid:
            if not best:
                best = process
            else:
                best = process if best.start_time < process.start_time else best
    return best

@app.route("/")
def graph():
    g = Graph('unix', filename='process',engine='dot')
    def traverse_internal(node):
        if node is None:
            return
        for child in node.children:
            g.edge(str(node),str(child))
            traverse_internal(child)

    init = get_pid_object(0)
    traverse_internal(init)
    return render_template('svgtest.html', chart_output=g.source)


def start_flask():
    socketio.run(app,host='0.0.0.0',port=8888, debug=False, use_reloader=False)


x = threading.Thread(target=start_flask, daemon=True) #daemon biar thread flask clean
x.start()


panda.queue_async(run_commands)
panda.run()
thread_stop_event.set() #untuk menghentikan emits



