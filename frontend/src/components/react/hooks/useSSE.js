import { useEffect, useState } from 'react';

export function useSSE(createStream, enabled) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      return undefined;
    }

    const stream = createStream();
    stream.onopen = () => setConnected(true);
    // Do NOT close the stream on error. A native EventSource auto-reconnects
    // after a transient error as long as it is left open — closing it here would
    // permanently drop the campaign event stream mid-run (pipelines take minutes).
    stream.onerror = () => setConnected(false);
    stream.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        setEvents((prev) => [...prev.slice(-79), payload]);
      } catch {
        setEvents((prev) => [...prev.slice(-79), { raw: event.data }]);
      }
    };

    return () => {
      stream.close();
      setConnected(false);
    };
  }, [createStream, enabled]);

  return { events, connected };
}
