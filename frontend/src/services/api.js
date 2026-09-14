const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000/api";

export const CONTENT_BASE_URL =
  import.meta.env.VITE_CONTENT_BASE_URL || "http://127.0.0.1:8000/content";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.detail || `请求失败（${response.status}）`);
  }
  return data;
}

function adminHeaders(token) {
  return token
    ? { Authorization: `Bearer ${token}` }
    : {};
}

export function adminLogin(username, password) {
  return request("/admin/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function getAdminRooms(token) {
  return request("/admin/rooms", {
    headers: adminHeaders(token),
  });
}

export function getAdminRoom(roomId, token) {
  return request(`/admin/rooms/${encodeURIComponent(roomId)}`, {
    headers: adminHeaders(token),
  });
}

export const getScripts = () => request("/scripts");
export const getWaitingRooms = () => request("/rooms");

export function createRoom({ scriptId, hostName }) {
  return request("/rooms", {
    method: "POST",
    body: JSON.stringify({ script_id: scriptId, host_name: hostName }),
  });
}

export function joinRoom(roomId, name) {
  return request(`/rooms/${encodeURIComponent(roomId)}/join`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export const getRoom = (roomId) =>
  request(`/rooms/${encodeURIComponent(roomId)}`);
export const getRoomPlayers = (roomId) =>
  request(`/rooms/${encodeURIComponent(roomId)}/players`);

export function startRoom(roomId, hostPlayerId) {
  return request(`/rooms/${encodeURIComponent(roomId)}/start`, {
    method: "POST",
    body: JSON.stringify({ host_player_id: hostPlayerId }),
  });
}

export function exitRoom(roomId, playerId) {
  return request(`/rooms/${encodeURIComponent(roomId)}/exit`, {
    method: "POST",
    body: JSON.stringify({ player_id: playerId }),
  });
}

export const getMyCharacter = (roomId, playerId) =>
  request(`/rooms/${encodeURIComponent(roomId)}/players/${encodeURIComponent(playerId)}/character`);
export const getGameState = (roomId) =>
  request(`/rooms/${encodeURIComponent(roomId)}/state`);
export const getMyClues = (roomId, playerId) =>
  request(`/rooms/${encodeURIComponent(roomId)}/players/${encodeURIComponent(playerId)}/clues`);
export const getMessages = (roomId, playerId) =>
  request(`/rooms/${encodeURIComponent(roomId)}/messages?${new URLSearchParams({ player_id: playerId })}`);

export const getVoteStatus = (roomId, playerId) =>
  request(`/rooms/${encodeURIComponent(roomId)}/vote?${new URLSearchParams({ player_id: playerId })}`);

export function castVote(roomId, playerId, suspectId) {
  return request(`/rooms/${encodeURIComponent(roomId)}/vote`, {
    method: "POST",
    body: JSON.stringify({
      player_id: playerId,
      suspect_id: suspectId,
    }),
  });
}
