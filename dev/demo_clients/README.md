# AZFlow demo clients

Static browser clients used to demonstrate AZFlow workflows. They are served by
AZFlow only from a source checkout and are not included in the Python package.

Start the development environment and open:

- `/demo/operator/?room=1&queue=1`
- `/demo/totem/`
- `/demo/room_display/?monitor=1`
- `/demo/waiting_room/?monitor=1`

Open as many operator, room display and waiting-room display instances as
needed. Each instance is configured by its URL parameters, so different tabs
can represent different Rooms, Queues and monitors independently.

The deterministic development seed provides RoomMonitor ids 1-3,
WaitingRoomMonitor ids 1-4, Rooms 1-3 and Totem `TOTEM-1`.
