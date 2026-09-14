export class WebRTCVoiceClient {
  constructor({
    websocket,
    playerId,
    iceServers = [],
    onRemoteStream = () => {},
    onPeerState = () => {},
  }) {
    this.websocket = websocket;
    this.playerId = playerId;
    this.iceServers = iceServers;
    this.onRemoteStream = onRemoteStream;
    this.onPeerState = onPeerState;
    this.localStream = null;
    this.startPromise = null;
    this.muted = true;
    this.peers = new Map();
  }

  async start({ muted = this.muted } = {}) {
    this.muted = muted;

    if (!this.localStream && !this.startPromise) {
      this.startPromise = navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
        video: false,
      }).then((stream) => {
        this.localStream = stream;
        return stream;
      }).finally(() => {
        this.startPromise = null;
      });
    }

    if (this.startPromise) {
      await this.startPromise;
    }

    this.setMuted(this.muted);
    return this.localStream;
  }

  async handleSignalMessage(message) {
    switch (message.type) {
      case "VOICE_PEERS":
        for (const remotePlayerId of message.player_ids || []) {
          if (this.shouldInitiate(remotePlayerId)) {
            await this.createOffer(remotePlayerId);
          }
        }
        break;
      case "VOICE_PEER_JOINED":
        if (this.shouldInitiate(message.player_id)) {
          await this.createOffer(message.player_id);
        }
        break;
      case "VOICE_PEER_LEFT":
        this.closePeer(message.player_id);
        break;
      case "WEBRTC_OFFER":
        await this.handleOffer(message.from_player_id, message.offer);
        break;
      case "WEBRTC_ANSWER":
        await this.handleAnswer(message.from_player_id, message.answer);
        break;
      case "WEBRTC_ICE_CANDIDATE":
        await this.handleCandidate(message.from_player_id, message.candidate);
        break;
      default:
        break;
    }
  }

  shouldInitiate(remotePlayerId) {
    return String(this.playerId) < String(remotePlayerId);
  }

  async createPeer(remotePlayerId) {
    let peer = this.peers.get(remotePlayerId);
    if (peer) return peer;

    peer = {
      connection: new RTCPeerConnection({
        iceServers: this.iceServers,
      }),
      pendingCandidates: [],
    };

    if (!this.localStream) {
      await this.start();
    }

    for (const track of this.localStream.getTracks()) {
      peer.connection.addTrack(track, this.localStream);
    }

    peer.connection.onicecandidate = (event) => {
      if (event.candidate) {
        this.sendSignal({
          type: "WEBRTC_ICE_CANDIDATE",
          target_player_id: remotePlayerId,
          candidate: event.candidate,
        });
      }
    };

    peer.connection.ontrack = (event) => {
      const stream = event.streams[0];
      if (stream) this.onRemoteStream(remotePlayerId, stream);
    };

    peer.connection.onconnectionstatechange = () => {
      const state = peer.connection.connectionState;
      this.onPeerState(remotePlayerId, state);
      if (["failed", "closed", "disconnected"].includes(state)) {
        this.closePeer(remotePlayerId);
      }
    };

    this.peers.set(remotePlayerId, peer);
    return peer;
  }

  async createOffer(remotePlayerId) {
    const peer = await this.createPeer(remotePlayerId);
    if (peer.connection.signalingState !== "stable") return;

    const offer = await peer.connection.createOffer();
    await peer.connection.setLocalDescription(offer);
    this.sendSignal({
      type: "WEBRTC_OFFER",
      target_player_id: remotePlayerId,
      offer: peer.connection.localDescription,
    });
  }

  async handleOffer(remotePlayerId, offer) {
    const peer = await this.createPeer(remotePlayerId);
    await peer.connection.setRemoteDescription(offer);
    await this.flushCandidates(peer);

    const answer = await peer.connection.createAnswer();
    await peer.connection.setLocalDescription(answer);
    this.sendSignal({
      type: "WEBRTC_ANSWER",
      target_player_id: remotePlayerId,
      answer: peer.connection.localDescription,
    });
  }

  async handleAnswer(remotePlayerId, answer) {
    const peer = this.peers.get(remotePlayerId);
    if (!peer || peer.connection.signalingState !== "have-local-offer") {
      return;
    }

    await peer.connection.setRemoteDescription(answer);
    await this.flushCandidates(peer);
  }

  async handleCandidate(remotePlayerId, candidate) {
    const peer = await this.createPeer(remotePlayerId);
    if (!peer.connection.remoteDescription) {
      peer.pendingCandidates.push(candidate);
      return;
    }

    await peer.connection.addIceCandidate(candidate);
  }

  async flushCandidates(peer) {
    for (const candidate of peer.pendingCandidates) {
      await peer.connection.addIceCandidate(candidate);
    }
    peer.pendingCandidates = [];
  }

  sendSignal(message) {
    if (this.websocket?.readyState !== WebSocket.OPEN) return;
    this.websocket.send(JSON.stringify(message));
  }

  setMuted(muted) {
    this.muted = muted;
    for (const track of this.localStream?.getAudioTracks() || []) {
      track.enabled = !muted;
    }
  }

  closePeer(remotePlayerId) {
    const peer = this.peers.get(remotePlayerId);
    if (!peer) return;
    peer.connection.close();
    this.peers.delete(remotePlayerId);
  }

  close() {
    for (const remotePlayerId of this.peers.keys()) {
      this.closePeer(remotePlayerId);
    }
    for (const track of this.localStream?.getTracks() || []) {
      track.stop();
    }
    this.localStream = null;
    this.startPromise = null;
  }
}
