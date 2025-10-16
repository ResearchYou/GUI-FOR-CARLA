from PyQt5.QtCore import QObject, pyqtSignal
import random
import time
import json

class PacketSpammer(QObject):
    packet_generated = pyqtSignal(dict)

    def __init__(self):
        super().__init__()

        if not hasattr(self, 'packet_definitions'):
            try:
                with open("command_ID.json") as f:
                    data = json.load(f)
                    self.packet_definitions = data.get("can_id", {})
            except Exception as e:
                print("Eroare la deschiderea CAN_ID.json:", e)
                return

        self.running = True

    def run(self):
        import psutil
        import os
        process = psutil.Process(os.getpid())


        keys = list(self.packet_definitions.keys())
        self.running = True
        start = time.time()
        for _ in range(1000000): 
            if not self.running:
                break
            random_id = random.choice(keys)
            details = self.packet_definitions[random_id]

            max_val = details.get("max", 1)
            if isinstance(max_val, list):
                try:
                    max_val = max([int(x) for x in max_val if isinstance(x, (int, float))])
                except:
                    max_val = 1
            elif not isinstance(max_val, (int, float)):
                max_val = 1

            try:
                data_value = random.randint(0, int(max_val))
            except:
                data_value = 0

            packet = {
                "can_id": random_id,
                "src": "Tester",
                "dst": details.get("execution"),
                "name": details.get("name"),
                "level": details.get("level"),
                "type": details.get("type"),
                "period": details.get("period"),
                "datasize": details.get("datasize"),
                "min": details.get("min"),
                "max": details.get("max"),
                "carlaVar": details.get("carlaVar"),
                "data": data_value
            }

            self.packet_generated.emit(packet)
            time.sleep(0.000000000) # sleep for 1 nanoseconds to simulate packet generation delay
        end = time.time()
        print(f"Packet generation completed in {end - start:.2f} seconds.")
        ram = process.memory_info().rss / (1024 * 1024)
        cpu = process.cpu_percent(interval=None)
        print(f"[ pachete] RAM: {ram:.2f} MB | CPU: {cpu:.1f}%")