# AZFlow demo clients

Static browser clients used to demonstrate AZFlow workflows. They are served by
the development-only demo-web gateway and are not included in the Python
package.

Run poetry run poe dev, then open:

- http://localhost/demo/operator/?room=1&queue=1
- http://localhost/demo/totem/
- http://localhost/demo/room_display/?monitor=1
- http://localhost/demo/waiting_room/?monitor=1
- http://localhost/adminer/ for Adminer

AZFlow remains directly available on http://localhost:8000, including its
Swagger UI at http://localhost:8000/docs.

Open as many operator, room display and waiting-room display instances as
needed. Each instance is configured by its URL parameters, so different tabs
can represent different Rooms, Queues and monitors independently.

The deterministic development seed provides RoomMonitor ids 1-3,
WaitingRoomMonitor ids 1-4, Rooms 1-3 and Totem TOTEM-1.
