export class WebRTCVoiceClient {
  constructor({
    websocket,
    playerId,
    // Host candidates are enough for localhost/LAN tests, but not for players
    // behind different NATs. Public STUN servers let browsers discover their
    // reachable candidates before we add a TURN relay for restrictive NATs.
    iceServers = [
      { urls: "stun:stun.cloudflare.com:3478" },
      { urls: "stun:stun.l.google.com:19302" },
    ],
    onRemoteStream = () => {},
    onPeerState = () => {},
    onSpeakingChange = () => {},
  }) {
    this.websocket = websocket;
    this.playerId = playerId;
    this.iceServers = iceServers;
    this.onRemoteStream = onRemoteStream;
    this.onPeerState = onPeerState;
    this.onSpeakingChange = onSpeakingChange;
    this.localStream = null;
    this.startPromise = null;
    this.muted = true;
    this.peers = new Map();
    this.audioContext = null;
    this.speakingMonitors = new Map();
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
        this.monitorSpeaking(this.playerId, stream);
        return stream;
      }).finally(() => {
        this.startPromise = null;
      });
    }

    if (this.startPromise) {
      await this.startPromise;
    }

    this.setMuted(this.muted);
    await this.resumeAudioAnalysis();
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
      if (stream) {
        this.onRemoteStream(remotePlayerId, stream);
        this.monitorSpeaking(remotePlayerId, stream);
      }
    };

    peer.connection.onconnectionstatechange = () => {
      const state = peer.connection.connectionState;
      this.onPeerState(remotePlayerId, state);
      if (["failed", "closed", "disconnected"].includes(state)) {
        this.closePeer(remotePlayerId);
      }
    };

    peer.connection.oniceconnectionstatechange = () => {
      const state = peer.connection.iceConnectionState;
      if (state === "failed") {
        // Give the caller a useful state instead of silently leaving a dead
        // peer in the voice roster. A later reconnect can create a new peer.
        this.onPeerState(remotePlayerId, "failed");
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
    if (muted) this.setMonitorSpeaking(this.playerId, false);
  }

  ensureAudioContext() {
    if (this.audioContext) return this.audioContext;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return null;
    this.audioContext = new AudioContextClass();
    return this.audioContext;
  }

  async resumeAudioAnalysis() {
    const context = this.audioContext;
    if (context?.state === "suspended") {
      await context.resume().catch(() => {});
    }
  }

  setMonitorSpeaking(playerId, speaking) {
    const monitor = this.speakingMonitors.get(playerId);
    if (monitor && monitor.speaking === speaking) return;
    if (monitor) monitor.speaking = speaking;
    this.onSpeakingChange(playerId, speaking);
  }

  monitorSpeaking(playerId, stream) {
    if (!playerId || !stream?.getAudioTracks().length) return;
    this.stopSpeakingMonitor(playerId);

    const context = this.ensureAudioContext();
    if (!context) return;

    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.72;
    source.connect(analyser);

    const samples = new Uint8Array(analyser.fftSize);
    const monitor = {
      source,
      analyser,
      speaking: false,
      loudFrames: 0,
      lastLoudAt: 0,
      timer: null,
    };

    monitor.timer = window.setInterval(() => {
      analyser.getByteTimeDomainData(samples);
      let energy = 0;
      for (const sample of samples) {
        const normalized = (sample - 128) / 128;
        energy += normalized * normalized;
      }
      const volume = Math.sqrt(energy / samples.length);
      const now = performance.now();

      if (volume >= 0.035) {
        monitor.loudFrames += 1;
        monitor.lastLoudAt = now;
        if (monitor.loudFrames >= 2) this.setMonitorSpeaking(playerId, true);
      } else {
        monitor.loudFrames = 0;
        if (monitor.speaking && now - monitor.lastLoudAt > 420) {
          this.setMonitorSpeaking(playerId, false);
        }
      }
    }, 80);

    this.speakingMonitors.set(playerId, monitor);
    void this.resumeAudioAnalysis();
  }

  stopSpeakingMonitor(playerId) {
    const monitor = this.speakingMonitors.get(playerId);
    if (!monitor) return;
    window.clearInterval(monitor.timer);
    monitor.source.disconnect();
    monitor.analyser.disconnect();
    this.speakingMonitors.delete(playerId);
    if (monitor.speaking) this.onSpeakingChange(playerId, false);
  }

  closePeer(remotePlayerId) {
    const peer = this.peers.get(remotePlayerId);
    this.stopSpeakingMonitor(remotePlayerId);
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
    for (const playerId of [...this.speakingMonitors.keys()]) {
      this.stopSpeakingMonitor(playerId);
    }
    this.audioContext?.close().catch(() => {});
    this.audioContext = null;
    this.localStream = null;
    this.startPromise = null;
  }
}
