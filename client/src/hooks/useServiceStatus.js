import { useState, useEffect, useCallback, useRef } from 'react';

/**
 * Is the chatbot in service, or has an operator taken it out?
 *
 * WHY THIS EXISTS
 *   Operator, 2026-08-13, after the first kill-switch drill: "when the bot
 *   has been shut down, a user cannot be expected to send a message to find
 *   out". That was exactly the behaviour -- the pause was enforced on the
 *   socket's message handler, so the widget loaded normally, the three
 *   launcher buttons looked live, and the ONLY way to discover the bot was
 *   out of service was to type a question and read the reply.
 *
 *   This polls the public `/health/service` endpoint so the UI can say it up
 *   front, and so a pause that lands mid-session reaches someone who is
 *   sitting on an already-rendered page and never sends another message.
 *
 * DELIBERATELY SEPARATE FROM useServerHealth
 *   "An operator stopped the bot" and "the bot is broken" are different
 *   facts and deserve different words. Health drives "we're experiencing
 *   technical difficulties"; this drives "down for maintenance". Folding
 *   the pause into the health signal would have been less code and would
 *   have told patrons something untrue.
 *
 * FAILS OPEN
 *   A failed or malformed poll leaves `isPaused` false. A network blip must
 *   not paint a working bot as offline -- a real outage is already covered
 *   by the socket-disconnect path, which has its own message. The endpoint
 *   returns an explicit `in_service` for the same reason: a missing field
 *   reads as "in service", never as "paused".
 */
const POLL_MS = 20000;

const useServiceStatus = (pollInterval = POLL_MS) => {
  const [status, setStatus] = useState({
    isPaused: false,
    since: null,
    askUsUrl: 'https://www.lib.miamioh.edu/research/research-support/ask/',
    checked: false,
  });

  // Avoids setState on an unmounted component when a poll is in flight.
  const alive = useRef(true);

  const check = useCallback(async () => {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 5000);
      const response = await fetch('/health/service', {
        signal: controller.signal,
        headers: { 'Cache-Control': 'no-cache', Pragma: 'no-cache' },
      });
      clearTimeout(timer);
      if (!response.ok) throw new Error(`status ${response.status}`);
      const data = await response.json();
      if (!alive.current) return;
      setStatus((prev) => ({
        // `paused === true` only. Anything else -- field absent, a proxy
        // error page, a string -- means in service. See "fails open".
        isPaused: data.paused === true,
        since: data.since || null,
        askUsUrl: data.ask_us_url || prev.askUsUrl,
        checked: true,
      }));
    } catch (error) {
      if (!alive.current) return;
      // Not console.error: during a real outage this fires every 20s and
      // would bury anything genuinely worth seeing in the console.
      console.warn('Service status check failed, assuming in service:', error.message);
      setStatus((prev) => ({ ...prev, isPaused: false, checked: true }));
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    check();
    const interval = setInterval(check, pollInterval);

    // Someone who left the tab open over lunch gets the current state when
    // they come back, rather than up to a full poll interval of stale UI.
    const onVisible = () => {
      if (document.visibilityState === 'visible') check();
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      alive.current = false;
      clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [check, pollInterval]);

  return { ...status, recheck: check };
};

export default useServiceStatus;
