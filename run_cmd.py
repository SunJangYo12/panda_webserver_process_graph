#!/usr/bin/env python3
'''
run_cmd.py

This example queues an asynchronous task to run various bash commands and print
them to the screen.

Run with: python3 run_cmd.py
'''

from pandare import Panda


panda = Panda("x86_64", mem="1G",qcow="/root/GIT/mydocker/bak/bionic-server-cloudimg-amd64-noaslr-nokaslr.qcow2",
            expect_prompt=rb"root@ubuntu:.*",
            extra_args=["-nographic",
            "-net", "nic,netdev=net0",
            "-netdev", "user,id=net0,",
            ])
panda.set_os_name("linux-64-ubuntu:4.15.0-72-generic-noaslr-nokaslr")




@panda.queue_blocking
def run_cmd():
    # First revert to root snapshot, then type a command via serial
    panda.revert_sync("myroot")
    print(panda.run_serial_cmd("uname -a"))

    print("Finding cat in cat's memory map:")
    maps = panda.run_serial_cmd("cat /proc/self/maps")
    for line in maps.split("\n"):
        if "cat" in line:
            print(line)
    panda.end_analysis()

panda.run()
