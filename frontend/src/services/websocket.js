const defaultWsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
const DEFAULT_WS_BASE_URL =
  import.meta.env.VITE_WS_BASE_URL ||
  defaultWsProtocol + "//" + window.location.host + "/api";

export class RoomWebSocket {
  constructor({ roomId, playerId, baseUrl = DEFAULT_WS_BASE_URL }) {
    this.roomId = roomId;
    this.playerId = playerId;
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.socket = null;
    this.reconnectTimer = null;
    this.reconnectAttempts = 0;
    this.manualClose = false;
    this.handlers = { open: [], message: [], close: [], error: [] };
  }

  get readyState() {
    return this.socket?.readyState ?? WebSocket.CLOSED;
  }

  get url() {
    return `${this.baseUrl}/rooms/${encodeURIComponent(this.roomId)}/ws?player_id=${encodeURIComponent(this.playerId)}`;
  }

  on(eventName, handler) {
    if (!this.handlers[eventName]) throw new Error(`不支持的事件：${eventName}`);
    this.handlers[eventName].push(handler);
    return () => {
      this.handlers[eventName] = this.handlers[eventName].filter((item) => item !== handler);
    };
  }

  emit(eventName, payload) {
    for (const handler of this.handlers[eventName] || []) handler(payload);
  }

  connect() {
    this.manualClose = false;
    if (this.socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(this.socket.readyState)) {
      return this.socket;
    }

    this.socket = new WebSocket(this.url);
    this.socket.addEventListener("open", (event) => {
      this.reconnectAttempts = 0;
      this.emit("open", event);
    });
    this.socket.addEventListener("message", (event) => {
      try {
        this.emit("message", JSON.parse(event.data));
      } catch (error) {
        this.emit("error", error);
      }
    });
    this.socket.addEventListener("error", (event) => this.emit("error", event));
    this.socket.addEventListener("close", (event) => {
      this.emit("close", event);
      this.scheduleReconnect();
    });
    return this.socket;
  }

  scheduleReconnect() {
    if (this.manualClose || this.reconnectTimer || this.reconnectAttempts >= 8) return;
    const delay = Math.min(800 * 2 ** this.reconnectAttempts, 6000);
    this.reconnectAttempts += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  send(message) {
    if (this.readyState !== WebSocket.OPEN) return false;
    this.socket.send(typeof message === "string" ? message : JSON.stringify(message));
    return true;
  }

  sendJson(message) {
    return this.send(message);
  }

  close() {
    this.manualClose = true;
    if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(this.socket.readyState)) {
      this.socket.close();
    }
  }
}
