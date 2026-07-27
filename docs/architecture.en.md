# Architecture

Sound receives RTP L16 playback data from Orchestrator and returns stream state through the canonical control plane. It is mode agnostic, so system modes do not alter its contract. Sound has no peer to peer connection with the other services or frontend.
