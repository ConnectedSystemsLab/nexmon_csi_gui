CC=gcc
TARGETS=makecsiparams unpack_float_py.so

all: $(TARGETS) 

makecsiparams: utils/makecsiparams/makecsiparams.c utils/makecsiparams/bcmwifi_channels.c
	$(CC) -o $@ $^ -I./utils/makecsiparams/

unpack_float_py.so: utils/matlab/unpack_float_py.c
	$(CC) -o $@ $^ -shared

.PHONY: clean

clean:
	rm -rf $(TARGETS) 
