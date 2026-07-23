import { useCallback, useEffect, useRef, useState } from 'react';

export function useWebSocket(createSocket, { onMessage, enabled = true } = {}) {
  const socketRef = useRef(null);
  const reconnectRef = useRef(null);
  const retriesRef = useRef(0);
  const [connected, setConnected] = useState(false);

  const connect = useCallback(() => {
    const socket = createSocket();
    socketRef.current = socket;

    socket.onopen = () => {
      retriesRef.current = 0;
      setConnected(true);
    };

    socket.onclose = () => {
      setConnected(false);
      const retryDelayMs = Math.min(1000 * 2 ** retriesRef.current, 8000);
      retriesRef.current += 1;
      reconnectRef.current = setTimeout(connect, retryDelayMs);
    };

    socket.onerror = () => {
      socket.close();
    };

    socket.onmessage = (event) => {
      if (!onMessage) return;
      try {
        const payload = JSON.parse(event.data);
        onMessage(payload);
      } catch {
        onMessage({ message: event.data });
      }
    };
  }, [createSocket, onMessage]);

  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      return undefined;
    }
    connect();
    return () => {
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (socketRef.current) socketRef.current.close();
    };
  }, [connect, enabled]);

  const send = useCallback((payload) => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) return false;
    socketRef.current.send(JSON.stringify(payload));
    return true;
  }, []);

  return { connected, send };
}
