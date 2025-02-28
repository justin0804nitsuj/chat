import socket
import threading

HOST = "0.0.0.0"  # 監聽所有網路介面
PORT = 12345      # 你可以自行調整埠號

clients = []
clients_lock = threading.Lock()

def broadcast(message, sender_socket):
    with clients_lock:
        for client in clients:
            # 不傳給發送者（或也可傳送回去，依需求而定）
            if client != sender_socket:
                try:
                    client.sendall(message)
                except Exception as e:
                    print("傳送訊息失敗:", e)
                    clients.remove(client)

def handle_client(client_socket, addr):
    print("新連線:", addr)
    with client_socket:
        while True:
            try:
                data = client_socket.recv(1024)
                if not data:
                    break
                print(f"從 {addr} 收到: {data.decode('utf-8')}")
                broadcast(data, client_socket)
            except Exception as e:
                print("連線錯誤:", e)
                break
    with clients_lock:
        if client_socket in clients:
            clients.remove(client_socket)
    print("連線關閉:", addr)

def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"聊天伺服器啟動：{HOST}:{PORT}")
    try:
        while True:
            client_socket, addr = server_socket.accept()
            with clients_lock:
                clients.append(client_socket)
            threading.Thread(target=handle_client, args=(client_socket, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("伺服器關閉")
    finally:
        server_socket.close()

if __name__ == "__main__":
    main()
