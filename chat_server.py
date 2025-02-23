import socket
import threading
import datetime
import base64

HOST = '127.0.0.1'
PORT = 55555

clients = []
nicknames = []
avatars = {}

def broadcast(message):
    for client in clients:
        client.send(message)

def handle(client):
    while True:
        try:
            message = client.recv(1024).decode('utf-8')
            if message.startswith('REGISTER'):
                _, nickname, avatar = message.split('|')
                nicknames.append(nickname)
                avatars[nickname] = avatar
                broadcast(f'{nickname} 加入了聊天室！'.encode('utf-8'))
            elif message.startswith('MESSAGE'):
                _, content = message.split('|')
                nickname = nicknames[clients.index(client)]
                avatar = avatars[nickname]
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                broadcast(f'MESSAGE|{nickname}|{avatar}|{timestamp}|{content}'.encode('utf-8'))
            elif message.startswith('FILE'):
                _, filename, filesize, file_base64, content = message.split('|')
                nickname = nicknames[clients.index(client)]
                avatar = avatars[nickname]
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                broadcast(f'FILE|{nickname}|{avatar}|{timestamp}|{filename}|{filesize}|{file_base64}|{content}'.encode('utf-8'))
        except:
            index = clients.index(client)
            clients.remove(client)
            client.close()
            nickname = nicknames[index]
            broadcast(f'{nickname} 離開了聊天室！'.encode('utf-8'))
            nicknames.remove(nickname)
            break

def receive():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()

    while True:
        client, address = server.accept()
        print(f'Connected with {str(address)}')

        clients.append(client)

        thread = threading.Thread(target=handle, args=(client,))
        thread.start()

print('Server is listening...')
receive()