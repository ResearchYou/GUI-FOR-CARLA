from PyQt5.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsEllipseItem
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QBrush, QColor
from constants import COLOR_MAP_BY_CAN_ID


class CanNetworkVisualizer(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setWindowTitle("CAN Network Visualizer")
        self.setGeometry(100, 100, 500, 400)

        self.modules = {
            "CGW": self.add_module(200, 20, "CGW"),
            "Tester": self.add_module(400, 20, "Tester"),
            "body": self.add_module(100, 150, "body"),
            "chasis": self.add_module(250, 150, "chasis"),
            "power train": self.add_module(400, 150, "power train"),
        }

        self.active_packets = []
        self.packet_timer = QTimer()
        self.packet_timer.timeout.connect(self.animate_packets)
        self.packet_timer.start(30)

    def add_module(self, x, y, label):
        rect = QGraphicsRectItem(x, y, 80, 40)
        rect.setBrush(QBrush(QColor("#cce5ff")))
        self.scene.addItem(rect)

        text = self.scene.addText(label)
        text.setDefaultTextColor(QColor("black"))
        text.setPos(x + 10, y - 20)

        return rect



    def send_packet(self, src, dst, can_id=None):
        if src not in self.modules or dst not in self.modules:
            print(f"404")
            return

        start = self.modules[src].sceneBoundingRect().center()
        end = self.modules[dst].sceneBoundingRect().center()

        color = COLOR_MAP_BY_CAN_ID.get(str(can_id), "#6c757d")

        packet = QGraphicsEllipseItem(0, 0, 12, 12)
        packet.setBrush(QBrush(QColor(color)))
        packet.setPos(start)
        self.scene.addItem(packet)

        steps = 25
        dx = (end.x() - start.x()) / steps
        dy = (end.y() - start.y()) / steps

        self.active_packets.append({
            "item": packet,
            "dx": dx,
            "dy": dy,
            "count": 0,
            "steps": steps
        })


    def animate_packets(self):
        for packet in self.active_packets[:]:
            item = packet["item"]
            if packet["count"] < packet["steps"]:
                item.moveBy(packet["dx"], packet["dy"])
                packet["count"] += 1
            else:
                self.scene.removeItem(item)
                self.active_packets.remove(packet)
