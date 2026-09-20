# Socket.IO / Engine.IO protocol notes

Reverse-engineered from the official web client (`remotecontrol.elnur.es`) and
verified directly against `api-elnur.helki.com` on 2026-09-20 by driving the
protocol by hand from the browser. Everything below is measured, not inferred —
the timings in particular come from real sessions.

This is the reference for `custom_components/elnur_gabarron/socketio_coordinator.py`
— read it before changing the transport, the ping handling or the packet
framing there.

## Handshake

```
GET https://api-elnur.helki.com/socket.io/?token=<JWT>&dev_id=<DEV_ID>&EIO=3&transport=polling&t=<cache-buster>
```

```json
{"sid":"…","upgrades":["websocket"],"pingInterval":25000,"pingTimeout":60000}
```

The server advertises a WebSocket upgrade and has done so consistently. The
official web client takes it: it issues polling requests for roughly the first
1.3 s of a page load and then goes quiet on HTTP entirely. It also keeps **two
parallel sessions** open — the server does not object to more than one session
per account.

## Engine.IO v3 pings are client-initiated

This is the single most important detail, and it is the opposite of Engine.IO
v4, which most documentation and most people's muscle memory describe.

With `EIO=3`, **the client sends `2` every `pingInterval` and the server replies
`3`**. The server never pings. It keeps its own idle timer, resets it on every
packet it receives, and closes the session once `pingInterval + pingTimeout`
elapses without hearing anything.

Measured, on an upgraded WebSocket where the client deliberately sent nothing:

```
  0.2s  <- dev_data
 85.3s  WS CLOSE code=1000 wasClean=true      (25s + 60s, to the decimal)
```

Zero `2` packets arrived from the server in those 85 seconds. The close is
clean, so it looks like an ordinary disconnect rather than an error — which is
exactly why it is easy to misread as "the server cycles sessions periodically".
It does not; it was waiting for a ping that never came.

The same session, pinging every 25 s:

```
 25.7s  -> 2   <- 3
 50.7s  -> 2   <- 3
 75.7s  -> 2   <- 3
100.7s  -> 2   <- 3      still open
```

Two consequences for a client:

- Ping on a fixed `pingInterval` schedule. Do **not** wait for the pong before
  scheduling the next ping: that stretches the real cadence to
  `pingInterval + pingTimeout`, which is precisely the server's own deadline,
  and whether the next ping lands first becomes a coin flip.
- A pong is sufficient proof that the connection is alive. Do not additionally
  require application data to arrive within some window — a house where nothing
  changes for a few minutes is a normal house, not a dead socket.

## Polling packets must be length-prefixed

On the polling transport every POST body is an Engine.IO payload:
`<length>:<packet>`. That is `1:2` for a ping, `1:3` for a pong, and
`<len>:42/api/v2/socket_io,["dev_data"]` for an event.

Sending a bare packet does not merely get ignored — **it destroys the session**:

```
POST body "1:2"  -> 200 "ok",  next GET returns  …40 …3      (pong, as expected)
POST body "2"    -> request fails at the network layer
                    next GET -> 400 {"code":1,"message":"Session ID unknown"}
```

This is worth knowing because it produces a very recognisable failure mode: the
session dies mid-poll, the next poll 500s or 400s, the client reconnects, and
the cycle repeats every few tens of seconds for as long as the client keeps
answering with unframed packets.

## Upgrade sequence

Standard Engine.IO v3 upgrade, confirmed end to end:

```
  ->  wss://api-elnur.helki.com/socket.io/?token=…&dev_id=…&EIO=3&transport=websocket&sid=<sid>
  ->  2probe
  <-  3probe
  ->  5                       (upgrade confirmed)
  <-  40
  <-  40/api/v2/socket_io
  <-  42/api/v2/socket_io,["dev_data",{…}]
```

The namespace join (`40/api/v2/socket_io?token=…&dev_id=…`) and the initial
`dev_data` request can be POSTed over polling before the upgrade; the server
carries the subscription across and delivers the response on whichever
transport is current.

**That last point matters:** once the session has upgraded, `dev_data` arrives
over the WebSocket. A client that requests `dev_data` and then waits for it with
an HTTP poll GET will wait forever and conclude the device has no zones.

## Cache busting

Every polling request from the official client carries a `t=` parameter. Worth
mirroring so an intermediate proxy never serves a stale response to a GET that
is semantically a queue read.
