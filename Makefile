CC = gcc
CFLAGS = -O2 -Wall -Wextra -pthread

.PHONY: all server client clean test
all: server client
server: build/chat_server
client: build/chat_client
build:
	mkdir -p build
build/chat_server: src/chat_server.c | build
	$(CC) $(CFLAGS) $< -o $@
build/chat_client: src/chat_client.c | build
	$(CC) $(CFLAGS) $< -o $@
test: all
	python3 -m unittest discover -s tests -v
clean:
	rm -f build/chat_server build/chat_client
