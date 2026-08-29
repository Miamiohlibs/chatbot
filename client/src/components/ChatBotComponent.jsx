import { useContext, useRef, useEffect, useState, useCallback } from 'react';
import { AlertTriangle, Clock } from 'lucide-react';
import MessageComponents from './ParseLinks';
import { SocketContext } from '../context/SocketContextProvider';
import { MessageContext } from '../context/MessageContextProvider';
import MessageRatingComponent from './MessageRatingComponent';
import HumanLibrarianWidget from './HumanLibrarianWidget';
import OfflineTicketWidget from './TicketWidget';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import './ChatBotComponent.css';

// `isPaused` -- an operator has taken the bot out of service. The transcript
// stays on screen (a student mid-conversation should not lose what they have
// read), but there is nothing useful to send: the server answers every turn
// with a maintenance notice. So the composer is disabled and says why,
// instead of accepting a question and returning a canned reply.
const ChatBotComponent = ({ askUsStatus = { isOpen: false, known: false, hoursToday: null, nextOpen: null }, isPaused = false }) => {
  // "We have not been able to check" is not "the desk is closed". Rendering
  // the first as the second told patrons librarian chat was offline during a
  // backend restart, on a weekday afternoon. Where the difference matters,
  // offer the librarian rather than asserting a closure we cannot support.
  const chatMaybeOpen = askUsStatus.isOpen || askUsStatus.known === false;
  const { socketContextValues } = useContext(SocketContext);
  const { messageContextValues } = useContext(MessageContext);
  const chatRef = useRef();
  // Focus goes back here after every send. The review reported that on a
  // multi-question chat "keyboard focus appears to get lost and starts at
  // the top" -- which is what happens whenever the focused element is
  // unmounted or disabled mid-turn, and a transcript that re-renders on
  // every message has several ways to do that. Rather than chase which
  // one, put focus somewhere correct on purpose: after sending a message
  // the next thing a person wants is the box they type the next one in.
  const inputRef = useRef(null);
  const [widgetVisible, setWidgetVisible] = useState(false);
  const [showTicketForm, setShowTicketForm] = useState(false);
  const [elapsedTime, setElapsedTime] = useState(0);

  // Live timer effect - updates every second while thinking
  useEffect(() => {
    let interval;
    if (messageContextValues.isTyping && messageContextValues.thinkingStartTime) {
      // Update immediately
      setElapsedTime(Math.floor((Date.now() - messageContextValues.thinkingStartTime) / 1000));
      
      // Then update every second
      interval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - messageContextValues.thinkingStartTime) / 1000);
        setElapsedTime(elapsed);
      }, 1000);
    } else {
      setElapsedTime(0);
    }
    
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [messageContextValues.isTyping, messageContextValues.thinkingStartTime]);

  // Did the patron actually FOLLOW a link we gave them?
  //
  // ONE DELEGATED LISTENER, not a callback threaded through the components.
  // Anchors are rendered in three different places -- markdown links inside
  // ParseLinks, the expandable CitationChip, and the "Sources" list below
  // each answer -- and a prop through all three would be three chances to
  // miss one. A listener on the transcript catches every anchor, including
  // any added later.
  //
  // Reported over the existing socket rather than a fetch: no new public
  // endpoint, and the connection is already bound to this conversation and
  // already rate-limited. The server drops anything whose URL was not in
  // that message's citations (see conversation_store.record_link_click).
  //
  // Deliberately does NOT preventDefault or delay: the click navigates
  // immediately as it always did. Losing a click record is fine; making a
  // patron wait on telemetry is not.
  // Reuses the existing `chatRef` on the transcript container -- a second
  // ref on the same node would just be another thing to keep in sync.
  useEffect(() => {
    const node = chatRef.current;
    const socket = socketContextValues.socket;
    if (!node || !socket) return undefined;
    const onClick = (e) => {
      try {
        const anchor = e.target && e.target.closest && e.target.closest('a[href]');
        if (!anchor || !node.contains(anchor)) return;
        const url = anchor.getAttribute('href') || '';
        if (!/^https?:/i.test(url)) return;   // ignore in-page anchors
        const holder = anchor.closest('[data-message-id]');
        socket.emit('linkClick', {
          url,
          messageId: holder ? holder.getAttribute('data-message-id') : undefined,
        });
      } catch {
        /* telemetry must never break navigation */
      }
    };
    node.addEventListener('click', onClick);
    return () => node.removeEventListener('click', onClick);
  }, [socketContextValues.socket]);

  const handleFormSubmit = (e) => {
    e.preventDefault();
    if (messageContextValues.inputMessage && socketContextValues.socket) {
      messageContextValues.addMessage(
        messageContextValues.inputMessage,
        'user',
      );
      messageContextValues.setInputMessage('');
      // Use startThinking to begin timer
      messageContextValues.startThinking();
      socketContextValues.sendUserMessage(messageContextValues.inputMessage);
      // After the re-render, not during it.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  };

  // Format time for display
  const formatTime = useCallback((seconds) => {
    if (seconds < 60) {
      return `${seconds}s`;
    }
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  }, []);

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight;
    }
  }, [messageContextValues.message]);

  // Determine if we should show service issues alert
  const shouldShowServiceAlert =
    !socketContextValues.serviceHealthy ||
    socketContextValues.connectionErrors >= 3 ||
    (!socketContextValues.isConnected &&
      socketContextValues.attemptedConnection);

  // Auto-show librarian widget based on service status
  useEffect(() => {
    if (socketContextValues.showLibrarianWidget && !widgetVisible) {
      setWidgetVisible(true);
    }
  }, [socketContextValues.showLibrarianWidget, widgetVisible]);

  return (
    <>
      {/* Service Status Alert */}
      {shouldShowServiceAlert && (
        <Alert variant="warning" className="mb-4">
          <AlertTriangle className="h-4 w-4" />
          <div className="flex-1">
            <AlertTitle>Service Issue Detected!</AlertTitle>
            <AlertDescription>
              {!socketContextValues.serviceHealthy
                ? 'The chatbot service is experiencing technical difficulties. '
                : 'Unable to connect to the chatbot service. '}
              {chatMaybeOpen
                ? 'Please talk to a librarian for immediate assistance.'
                : 'Please submit a ticket and we\'ll get back to you.'}
            </AlertDescription>
          </div>
          {chatMaybeOpen ? (
            <Button
              size="sm"
              variant="default"
              onClick={() => setWidgetVisible(!widgetVisible)}
            >
              {widgetVisible ? 'Hide' : 'Chat with a librarian'}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="default"
              onClick={() => setShowTicketForm(!showTicketForm)}
            >
              {showTicketForm ? 'Hide' : 'Submit a Ticket'}
            </Button>
          )}
        </Alert>
      )}

      {/* Librarian Widget - only shown during business hours */}
      {widgetVisible && chatMaybeOpen && (
        <div className="mb-4 p-4 border border-blue-200 rounded-md bg-blue-50">
          <div className="flex justify-between items-center mb-2">
            <span className="font-bold text-blue-700">
              Talk to a librarian
            </span>
            <Button
              size="xs"
              variant="ghost"
              aria-label="Close the librarian panel"
              onClick={() => setWidgetVisible(false)}
            >
              <span aria-hidden="true">✕</span>
            </Button>
          </div>
          <HumanLibrarianWidget />
        </div>
      )}

      {/* Ticket Form Widget - shown when librarian chat not available */}
      {showTicketForm && !chatMaybeOpen && (
        <div className="mb-4 p-4 border border-orange-200 rounded-md bg-orange-50">
          <div className="flex justify-between items-center mb-2">
            <span className="font-bold text-orange-700">
              Submit a Ticket
            </span>
            <Button
              size="xs"
              variant="ghost"
              aria-label="Close the ticket form"
              onClick={() => setShowTicketForm(false)}
            >
              <span aria-hidden="true">✕</span>
            </Button>
          </div>
          <OfflineTicketWidget />
        </div>
      )}

      {/* role="log" + aria-live: without this a screen-reader user sends a
          question and never hears the answer -- nothing announces it.
          "polite" so it waits for a pause instead of cutting the user off;
          aria-atomic=false so only the NEW message is read, not the whole
          transcript again on every reply. */}
      <div
        ref={chatRef}
        className="chat"
        role="log"
        aria-live="polite"
        aria-atomic="false"
        aria-relevant="additions text"
        aria-label="Conversation with the Smart Chatbot"
      >
        <div className="flex flex-col items-start gap-4">
          {messageContextValues.message.map((message, index) => {
            const adjustedMessage =
              typeof message.text === 'object'
                ? message.text.response.join('')
                : message.text;

            // Strip any legacy "References:" tail from the body text (the
            // structured citations array supersedes it).
            const bodyText = adjustedMessage.split(/\nReferences:\n/i)[0] || '';

            // Structured confidence (v2) wins over text heuristic (legacy).
            const lowConfidenceHint =
              message.confidence === 'low' ||
              /No strong matches found|Institutional knowledge service is temporarily unavailable|ask a clarifying question/i.test(
                adjustedMessage,
              );
            // Reliability gate: when the answer is uncertain or a refusal,
            // do NOT surface sources -- strip inline [n] markers and drop the
            // citations so no clickable "evidence" appears under an answer the
            // bot itself flagged as unreliable.
            const showSources = !lowConfidenceHint;
            const renderBody = showSources
              ? bodyText
              : bodyText.replace(/\s*\[\d+\]/g, '');
            const renderCitations = showSources ? message.citations : undefined;
            return (
              <div
                key={index}
                /* Carries the message id so the delegated link-click listener
                   below can attribute a click to the answer it came from,
                   without threading a callback through ParseLinks AND
                   CitationChip -- both of which render anchors. */
                data-message-id={message.messageId || undefined}
                className={message.sender === 'user' ? 'self-end' : 'self-start'}
              >
                <div
                  className={`max-w-md px-5 py-3 rounded-md relative ${
                    message.sender === 'user'
                      ? 'bg-white border border-red-400'
                      : 'bg-gray-200'
                  } ${message.sender !== 'user' && message.responseTime != null ? 'bot-message-with-time' : ''}`}
                >
                  {/* Response time badge for bot messages */}
                  {message.sender !== 'user' && message.responseTime !== null && message.responseTime !== undefined && (
                    <div className="response-time-badge" title="Response time">
                      <Clock size={12} className="inline mr-1" />
                      {formatTime(message.responseTime)}
                    </div>
                  )}
                  {/* Which campus this answer is for, when the student did
                      not say and the answer differs between them. Above the
                      text on purpose: a Hamilton or Middletown student can
                      stop here instead of reading an answer written for
                      Oxford. It is a badge and not a sentence in the answer
                      because as prose it read as the bot asking a question
                      back, and it cost 10 of 150 graded cases. */}
                  {message.sender !== 'user' && message.campusAssumed && (
                    <div className="campus-assumed-badge">
                      For <strong>{message.campusAssumed}</strong> — other
                      campuses differ. Say which campus you&apos;re on for
                      theirs.
                    </div>
                  )}
                  <div
                    className={`whitespace-pre-line ${
                      message.sender === 'user' ? 'text-red-600' : 'text-black'
                    }`}
                  >
                    {typeof message.text === 'object' ? (
                      <div className="half-line-height">
                        <MessageComponents msg={renderBody} citations={renderCitations} />
                      </div>
                    ) : (
                      <MessageComponents msg={renderBody} citations={renderCitations} />
                    )}
                  </div>
                </div>
                {/* Sources footer (re-added 2026-06-16, operator request):
                    the inline [n] popover chip proved unclickable on the
                    embedded widget (portal popover + sandbox/popup quirks).
                    List the source links here instead, as small plain
                    anchors in normal document flow -- a real <a target=_blank>
                    that just navigates, no popover, right-click/copy work. */}
                {message.sender !== 'user' &&
                  renderCitations &&
                  renderCitations.length > 0 && (
                    <div className="mt-1 ml-1 px-4 text-[11px] leading-snug text-gray-500">
                      {/* A heading, not a bold span: the sources are a
                          section of the answer, and a screen reader user
                          navigating by heading had no way to reach them.
                          h3 because the answer sits under the dialog's
                          h2. Reported in the accessibility review. */}
                      <h3 className="font-semibold text-gray-600 text-[11px] m-0">
                        Sources
                      </h3>
                      <ul className="mt-0.5 space-y-0.5">
                        {renderCitations
                          .filter((c) => c && c.url)
                          .map((c, ci) => (
                            <li key={`src-${index}-${ci}`} className="flex gap-1">
                              <span className="shrink-0 text-gray-400">
                                [{c.n}]
                              </span>
                              <a
                                href={c.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="break-all text-blue-600 hover:underline"
                              >
                                {c.url}
                              </a>
                            </li>
                          ))}
                      </ul>
                    </div>
                  )}
                {/* Low-confidence handoff prompt REMOVED (operator request
                    2026-06-08): the auto-injected "This answer may be
                    uncertain / Submit a Ticket / Chat with Librarian" alert
                    is no longer shown under uncertain answers. The refusal
                    answer text itself already points the user to Ask Us, and
                    the operator runs a separate, user-initiated escalation
                    path. To restore, re-add an `Alert` gated on
                    `lowConfidenceHint` here. */}
                {message.sender !== 'user' && index !== 0 && (
                  <MessageRatingComponent message={message} />
                )}
              </div>
            );
          })}
          {messageContextValues.isTyping && (
            <div className="max-w-md px-5 py-3 rounded-md bg-gray-200 relative bot-message-with-time">
              <div className="thinking-timer" title="Time elapsed">
                <Clock size={14} className="inline mr-1 animate-pulse" />
                <span className="font-mono">{formatTime(elapsedTime)}</span>
              </div>
              <p>
                Chatbot is thinking <span className="dots"></span>
              </p>
            </div>
          )}
          {!socketContextValues.isConnected && (
            <div className="max-w-[350px] px-5 py-3 rounded-md bg-gray-200 self-start">
              <p className="text-black">
                Connecting to the chatbot <span className="dots"></span>
              </p>
            </div>
          )}
        </div>
      </div>

      <form onSubmit={handleFormSubmit}>
        <div className="flex gap-3">
          {/* A placeholder is not a label: it vanishes on the first keystroke
              and is not reliably exposed as the accessible name. Real label,
              visually hidden so the design is unchanged. */}
          <label htmlFor="chat-message-input" className="sr-only">
            Type your message to the Smart Chatbot
          </label>
          <Input
            ref={inputRef}
            id="chat-message-input"
            value={messageContextValues.inputMessage}
            onChange={(e) => messageContextValues.setInputMessage(e.target.value)}
            placeholder={
              isPaused
                ? 'Chatbot offline for maintenance'
                : 'Type your message...'
            }
            disabled={!socketContextValues.isConnected || isPaused}
            className="flex-1"
          />
          <Button
            variant="miami"
            type="submit"
            disabled={!socketContextValues.isConnected || isPaused}
          >
            Send
          </Button>
        </div>
      </form>
      {/* Librarians reported this read as fine print nobody sees, which is
          the opposite of what it is for -- it is the one line telling a
          student not to act on a wrong answer. Given weight: an alert
          role, a warning rule, an icon, and text at body size rather than
          text-xs grey. Colours are the AAA pair used elsewhere in the
          widget (#6b3a00 on #fff4e0, 8.6:1). */}
      <p role="note" className="chat-disclaimer">
        <AlertTriangle className="chat-disclaimer-icon" aria-hidden="true" />
        <span>
          <strong>The chatbot can be wrong.</strong> Check anything that
          matters with a librarian.
          {askUsStatus.isOpen
            ? ' Chat is open now.'
            : askUsStatus.known === false
              ? ''
              : askUsStatus.nextOpen
              ? ` Chat opens ${askUsStatus.nextOpen.when === 'later today'
                  ? '' : `${askUsStatus.nextOpen.when} `}at ${askUsStatus.nextOpen.time}.`
              : ' Submit a ticket and one will reply.'}
        </span>
      </p>
    </>
  );
};

export default ChatBotComponent;
