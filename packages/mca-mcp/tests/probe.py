"""
Which layer of the transport is silent?

Three sends to Maya's Python command port, each simpler than the last thing that failed, and
each leaving a file behind if it ran. Whatever the highest-numbered file that appears is,
that is how far the port gets.

    1  a bare write            - does the port execute anything at all
    2  maya.cmds in the handler - does touching Maya from the socket thread work
    3  executeDeferred          - does work queued to the main thread ever run
    4  the real wrapper         - the whole thing, exactly as the transport sends it

It also reads the socket back rather than closing immediately, and prints whatever Maya says
- which is where a SyntaxError would show up.
"""

import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

HOST = '127.0.0.1'
PORT = 7002
OUT = 'C:/Temp'


def send(label, payload, read_back=True):
    """Send one payload, optionally read whatever comes back, and say what happened."""

    print('--- {} ---'.format(label))
    print('    {} byte(s), {} line(s)'.format(len(payload), len(payload.splitlines())))
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(5.0)
    try:
        connection.connect((HOST, PORT))
    except Exception as error:
        print('    could not connect: {}'.format(error))
        return
    try:
        connection.sendall(payload.encode('utf-8') + b'\n')
        if read_back:
            connection.settimeout(6.0)
            chunks = []
            try:
                while True:
                    data = connection.recv(4096)
                    if not data:
                        break
                    chunks.append(data)
                    if len(b''.join(chunks)) > 40000:
                        break
            except socket.timeout:
                pass
            reply = b''.join(chunks).decode('utf-8', 'replace').strip('\x00').strip()
            print('    Maya said: {}'.format(reply[:600] if reply else '(nothing)'))
    finally:
        connection.close()


def check(number):
    path = os.path.join(OUT.replace('/', os.sep), 'mca_probe{}.txt'.format(number))
    if os.path.isfile(path):
        with open(path) as handle:
            print('    FILE {}: {!r}'.format(number, handle.read()[:200]))
        os.remove(path)
        return True
    print('    FILE {}: not written'.format(number))
    return False


def main():
    if not os.path.isdir(OUT.replace('/', os.sep)):
        os.makedirs(OUT.replace('/', os.sep))
    for number in (1, 2, 3, 4):
        path = os.path.join(OUT.replace('/', os.sep), 'mca_probe{}.txt'.format(number))
        if os.path.exists(path):
            os.remove(path)

    send('1: a bare write, one line, nothing to do with Maya',
         "open('{}/mca_probe1.txt', 'w').write('one')".format(OUT))
    time.sleep(1.5)
    check(1)

    send('2: maya.cmds straight from the socket handler',
         "import maya.cmds as cmds; open('{}/mca_probe2.txt', 'w').write(cmds.about(version=True))"
         .format(OUT))
    time.sleep(2.0)
    check(2)

    send('3: work queued onto the main thread with executeDeferred',
         "import maya.utils; maya.utils.executeDeferred("
         "lambda: open('{}/mca_probe3.txt', 'w').write('deferred'))".format(OUT))
    time.sleep(3.0)
    check(3)

    from mca.mcp.core import link

    program = link._wrapper("result = 'the real wrapper ran'\n",
                            '{}/mca_probe4.txt'.format(OUT))
    send('4: the transport\'s own program, exactly as it sends it', program)
    time.sleep(3.0)
    check(4)

    print('')
    print('Whatever the last file written was, that is where it stops.')


if __name__ == '__main__':
    main()
