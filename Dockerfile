FROM pandare/panda:9831d8ce597e62fefec8b3bc5ae2bd6957b8a010 
WORKDIR /panda
RUN git pull
RUN git checkout 29e9a3051f4498e86c4046874526d116cd2ffd96
WORKDIR /panda/build
RUN /bin/sh -c make clean
RUN /bin/sh -c ../build.sh
RUN /bin/sh -c make install
WORKDIR /panda/panda/python/core
RUN rm -rf /usr/local/lib/python3.6/dist-packages/panda
RUN python3 setup.py install
WORKDIR /
RUN git clone https://github.com/lacraig2/panda_webserver_process_graph 
WORKDIR /panda_webserver_process_graph
RUN git checkout 8d3cb740d2189b60917fc19e9b5fbca9d305f0bb
RUN python3 -m pip install flask flask-socketio graphviz
RUN wget -q https://panda-re.mit.edu/qcows/linux/ubuntu/1804/x86_64/bionic-server-cloudimg-amd64-noaslr-nokaslr.qcow2
