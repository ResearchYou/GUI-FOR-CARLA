import socket

TEENSY_IP = "10.0.0.2"
PORT = 23

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    try:
        s.connect((TEENSY_IP, PORT))
        print(f"Connected to {TEENSY_IP}:{PORT}")

        s.sendall((" ").encode())
        while True:
            data = s.recv(128).decode()
            print(data.strip())

    except TimeoutError:
        print(f"Connection to {TEENSY_IP}:{PORT} timed out")

    except KeyboardInterrupt:
        print("\nExited successfully")