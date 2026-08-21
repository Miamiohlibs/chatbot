import { useContext, useEffect, useRef, useState, useCallback } from 'react';
import { ArrowLeft, Clock, Wrench, X } from 'lucide-react';
import { toast } from 'sonner';
import HumanLibrarianWidget from './components/HumanLibrarianWidget';
import OfflineTicketWidget from './components/TicketWidget';
import ChatBotComponent from './components/ChatBotComponent';
import ErrorBoundaryComponent from './components/ErrorBoundaryComponent';
import { SocketContext } from './context/SocketContextProvider';
import FeedbackFormComponent from './components/FeedbackFormComponent';
import useServerHealth from './hooks/useServerHealth';
import useServiceStatus from './hooks/useServiceStatus';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

/**
 * "The chatbot is out of service" -- said in the UI, before anyone types.
 *
 * The kill switch used to be invisible until a patron sent a message and
 * got a maintenance reply. This is the same fact, stated up front, in the
 * two places a patron actually looks: the welcome layer and the launcher
 * panel.
 *
 * `role="status"` rather than `role="alert"`: a screen reader should hear
 * this when it appears mid-session (a pause landing while the page is
 * open), politely, without interrupting whatever is being read. It is not
 * an emergency, it is a change of state.
 *
 * Colours: miami-red-dark on red-50 measures 7.8:1, which clears the 7:1
 * this widget is held to (WCAG 2.1 AAA, 1.4.6). Do not lighten either one
 * without re-measuring.
 */
const OutOfServiceNotice = ({ askUsUrl, compact = false }) => (
  <div
    role="status"
    className={`offline-notice rounded-lg border-2 border-miami-red-dark bg-red-50 text-left ${
      compact ? 'p-3' : 'p-4'
    }`}
  >
    <p className="flex items-center gap-2 font-bold text-miami-red-dark">
      <Wrench className="h-4 w-4 shrink-0" aria-hidden="true" />
      Chatbot offline for maintenance
    </p>
    {/* Not "the options below": this same notice renders on the welcome
        layer, where there is nothing below it -- the buttons live inside
        the panel, one click away. Wording that is true in both places. */}
    <p className={`text-gray-900 ${compact ? 'text-sm mt-1' : 'mt-2'}`}>
      The Smart Chatbot is temporarily out of service. A librarian can still
      help you — you can create a ticket, or reach someone now through{' '}
      <a
        href={askUsUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="font-semibold text-miami-red-dark underline underline-offset-2"
      >
        Ask Us
      </a>
      .
    </p>
  </div>
);

const App = () => {
  const [isOpen, setIsOpen] = useState(true); // Open by default
  const [step, setStep] = useState('initial');
  const { socketContextValues } = useContext(SocketContext);
  const { serverStatus, needsAttention } = useServerHealth();
  // An operator-thrown kill switch, which is NOT the same thing as a fault.
  // See hooks/useServiceStatus.
  const { isPaused, askUsUrl } = useServiceStatus();
  
  // Ask Us Chat Service availability.
  //
  // `known` is the whole point of this shape. Without it a failed fetch left
  // isOpen at its initial false, and the widget told patrons "Librarian chat
  // is offline" during a backend restart -- at 2pm on a weekday, with
  // librarians sitting at the desk. Not knowing is not the same as knowing
  // the answer is no, and only one of those is safe to render.
  //
  // The last good answer is cached in sessionStorage so a reload mid-restart
  // keeps what we already learned instead of starting from ignorance again.
  const ASKUS_CACHE_KEY = 'askus-status-v1';
  const [askUsStatus, setAskUsStatus] = useState(() => {
    const blank = { isOpen: false, known: false, message: '',
                    hoursToday: null, nextOpen: null, loading: true };
    try {
      const raw = sessionStorage.getItem(ASKUS_CACHE_KEY);
      if (!raw) return blank;
      const cached = JSON.parse(raw);
      // Hours change on the hour; anything older than that is not worth
      // trusting over a fresh "we don't know".
      if (Date.now() - (cached.at || 0) > 60 * 60 * 1000) return blank;
      return { ...blank, ...cached.value, loading: true };
    } catch {
      return blank;
    }
  });

  const askUsRetries = useRef(0);

  // Fetch Ask Us Chat Service availability
  const checkAskUsAvailability = useCallback(async () => {
    try {
      const response = await fetch('/askus-hours/status');
      if (!response.ok) throw new Error(`status ${response.status}`);
      const data = await response.json();
      const value = {
        isOpen: data.is_open,
        known: true,
        message: data.message || '',
        hoursToday: data.hours_today,
        // When chat NEXT opens. Without it the closed state showed
        // TODAY's hours ("available 9:00am - 6:00pm") at 10pm, and a
        // student on a Friday evening could not tell a two-hour wait
        // from a 62-hour one.
        nextOpen: data.next_open || null,
      };
      askUsRetries.current = 0;
      try {
        sessionStorage.setItem(ASKUS_CACHE_KEY,
          JSON.stringify({ at: Date.now(), value }));
      } catch { /* private mode, or a full quota -- not worth failing over */ }
      setAskUsStatus({ ...value, loading: false });
    } catch (error) {
      console.error('Failed to check Ask Us availability:', error);
      // Keep whatever we already knew. Only the very first failure leaves
      // us in the unknown state, and the UI renders that as unknown.
      setAskUsStatus(prev => ({ ...prev, loading: false }));

      // A restart takes ~90s. Waiting the full five-minute poll to find
      // out the desk is staffed is how a two-minute outage became an
      // afternoon of "librarian chat is offline".
      const n = askUsRetries.current;
      if (n < 6) {
        askUsRetries.current = n + 1;
        setTimeout(() => { checkAskUsAvailability(); },
                   Math.min(30000, 2000 * Math.pow(2, n)));
      }
    }
  }, []);

  // Check availability on mount and every 5 minutes
  useEffect(() => {
    checkAskUsAvailability();
    const interval = setInterval(checkAskUsAvailability, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [checkAskUsAvailability]);

  useEffect(() => {
    if (
      !socketContextValues.isConnected &&
      socketContextValues.attemptedConnection
    ) {
      toast.error('Connection Error', {
        // A stable id makes sonner REPLACE the toast instead of stacking a
        // new one. This effect re-runs whenever any dependency changes while
        // the socket is down, which is how three identical "Connection Error"
        // cards ended up on screen at once.
        id: 'connection-error',
        description: askUsStatus.isOpen
          ? 'The Smart Chatbot is currently not available. Please talk to a librarian during business hours or create a ticket for help.'
          : 'The Smart Chatbot is currently not available. Please create a ticket and we\'ll get back to you.',
        // Persistent, not timed. The condition it reports does not go away
        // after nine seconds, and WCAG 2.2.1 (Timing Adjustable, Level A)
        // wants content that disappears on a timer to be dismissible or
        // extendable. The close button on <Toaster> is how it is dismissed.
        duration: Infinity,
      });
    }
  }, [
    socketContextValues.isConnected,
    socketContextValues.attemptedConnection,
    askUsStatus.isOpen,
  ]);

  // Auto-redirect based on server health and business hours
  useEffect(() => {
    if (
      (serverStatus === 'unhealthy' ||
        (!socketContextValues.isConnected &&
          socketContextValues.attemptedConnection)) &&
      isOpen &&
      step === 'services'
    ) {
      if (askUsStatus.isOpen || !askUsStatus.known) {
        toast.warning('Service Unavailable', {
          description:
            'The Smart Chatbot is currently unavailable. Redirecting you to a librarian for assistance.',
          duration: 5000,
        });
        setStep('humanLibrarian');
      } else {
        toast.warning('Service Unavailable', {
          description:
            'The Smart Chatbot is currently unavailable. Please submit a ticket and we\'ll get back to you.',
          duration: 5000,
        });
        setStep('ticket');
      }
    }
  }, [
    serverStatus,
    socketContextValues.isConnected,
    socketContextValues.attemptedConnection,
    isOpen,
    step,
    askUsStatus.isOpen,
  ]);

  // Handler for when user clicks "Talk to Librarian" from error boundary
  const handleLibrarianHelp = () => {
    if (!isOpen) {
      setIsOpen(true);
    }
    
    if (askUsStatus.isOpen || !askUsStatus.known) {
      setStep('humanLibrarian');
      toast.info('Connecting to Librarian', {
        description: 'Redirecting you to a librarian.',
        duration: 3000,
      });
    } else {
      setStep('ticket');
      toast.info('Submit a Ticket', {
        description: 'Librarian chat is currently offline. Please submit a ticket and we\'ll get back to you.',
        duration: 3000,
      });
    }
  };

  const handleClose = () => {
    setStep('initial');
    setIsOpen(false);
  };

  // Two different reasons the chatbot button must not be pressable, kept
  // apart on purpose: a fault ("technical difficulties") and an operator
  // decision ("down for maintenance"). Both disable the button; only one of
  // them is the bot's fault, and patrons are told which.
  const isChatbotFaulty =
    serverStatus === 'unhealthy' ||
    (!socketContextValues.isConnected && socketContextValues.attemptedConnection);
  const isChatbotUnavailable = isChatbotFaulty || isPaused;

  return (
    <ErrorBoundaryComponent onLibrarianHelp={handleLibrarianHelp}>
      {/* Welcome background.
          `inert` when the dialog is open: aria-hidden alone hid it from
          screen readers but left it in the tab order, so a keyboard user
          could still reach the content behind an open dialog. */}
      {/* flex-col so the out-of-service notice can be a SIBLING of the
          clickable welcome block rather than a child of it. It used to be
          inside, which put a link inside a role="button" -- axe flags that
          as `nested-interactive`, and it is a genuine trap: the Ask Us link
          was focusable inside a control that is itself one tab stop. */}
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center p-4">
        <div
          className={`text-center mb-8 transition-all duration-300 ${
            isOpen ? 'opacity-30' : 'opacity-100 cursor-pointer hover:opacity-80 hover:-translate-y-0.5'
          } ${!isOpen ? 'focus:outline-none focus:ring-4 focus:ring-blue-400/60 focus:scale-[1.02] focus:-translate-y-0.5 focus:bg-blue-500/5' : ''}`}
          onClick={!isOpen ? () => setIsOpen(true) : undefined}
          onKeyDown={!isOpen ? (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              setIsOpen(true);
            }
          } : undefined}
          inert={isOpen || undefined}
          tabIndex={!isOpen ? 0 : -1}
          role={!isOpen ? 'button' : undefined}
          aria-label={!isOpen ? 'Open Smart Chatbot services' : undefined}
        >
          <img
            src='https://libapps.s3.amazonaws.com/accounts/190074/images/0721_STier1_Libraries_HS_186KW_K_Digital.png'
            height={80}
            width={200}
            alt='library logo'
            className="mx-auto mb-5"
          />
          <h2 className="text-2xl font-bold text-gray-700 mb-2">
            Welcome to the Smart Chatbot
          </h2>
          <p className="text-base text-gray-600">
            Get help with quick information, or talk to a librarian for research questions.
          </p>
          {!isOpen && (
            /* blue-500 measured 3.59:1 on gray-50 -- it failed AA, never
               mind the AAA this widget is held to. It went unnoticed
               because it only renders with the panel CLOSED, and no audit
               had ever run against that state. blue-800 is 8.35:1. */
            <p className="text-sm text-blue-800 mt-3 font-semibold">
              {isPaused ? 'See your options' : 'Get Started'}
            </p>
          )}
        </div>
        {/* Only with the panel CLOSED. With it open the panel carries its
            own copy, and a second one out here would be a duplicate that
            is also un-dimmed (the opacity-30 belongs to the block above)
            and outside that block's `inert`, i.e. reachable by keyboard
            from behind an open dialog. */}
        {isPaused && !isOpen && (
          <div className="mb-8 max-w-md w-full">
            <OutOfServiceNotice askUsUrl={askUsUrl} />
          </div>
        )}
      </div>

      <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
        <DialogContent className="max-w-[450px] mx-4" hideClose>
          <DialogHeader className="flex flex-row items-center justify-between ps-0 pe-0">
            <div className="flex items-center gap-3">
              <img
                src='https://libapps.s3.amazonaws.com/accounts/190074/images/0721_STier1_Libraries_HS_186KW_K_Digital.png'
                height={50}
                width={120}
                alt='library logo'
              />
              <DialogTitle>Smart Chatbot</DialogTitle>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 -mr-2"
              aria-label="Close"
              onClick={handleClose}
            >
              <X className="h-4 w-4" />
            </Button>
          </DialogHeader>
          
          <div className="flex justify-between">
            {step !== 'initial' && (
              <Button
                variant="outline"
                size="xs"
                className="ml-[7%] text-miami-red-dark border-miami-red-dark hover:bg-miami-red-dark hover:text-white"
                onClick={() => setStep('initial')}
              >
                <ArrowLeft className="h-3 w-3 mr-1" />
                Back
              </Button>
            )}
            {step === 'services' && <FeedbackFormComponent />}
          </div>
          
          <div className="py-5">
            {step === 'initial' && (
              <div className="flex flex-col gap-3">
                {/* The three buttons used to look completely healthy while
                    the bot was out of service. Say it here, above them,
                    where the choice is actually made. The librarian and
                    ticket buttons stay live: taking the BOT out of service
                    must never take away the human routes -- those are the
                    whole point of pausing rather than stopping the
                    process. */}
                {isPaused && <OutOfServiceNotice askUsUrl={askUsUrl} compact />}
                <Button
                  variant="miami"
                  onClick={() => {
                    if (isChatbotUnavailable) {
                      toast.error('Chatbot Unavailable', {
                        description:
                          'The Smart Chatbot is currently unavailable. Please talk to a librarian during business hours or submit a ticket.',
                        duration: 5000,
                      });
                      if (askUsStatus.isOpen || !askUsStatus.known) {
                        setStep('humanLibrarian');
                      } else {
                        setStep('ticket');
                      }
                    } else {
                      setStep('services');
                    }
                  }}
                  disabled={isChatbotUnavailable}
                  className={isChatbotUnavailable ? 'opacity-60' : ''}
                >
                  Library Chatbot{' '}
                  {isPaused
                    ? '(Offline for maintenance)'
                    : (needsAttention ||
                        (!socketContextValues.isConnected &&
                          socketContextValues.attemptedConnection)) &&
                      '(Unavailable)'}
                </Button>
                
                {/* Three states, not two. `known === false` means the
                    status check has not succeeded yet -- during a backend
                    restart, say -- and claiming "offline" there sent
                    patrons to a ticket form while a librarian sat waiting.
                    Offer both and say we could not check. */}
                {!askUsStatus.known && !askUsStatus.loading ? (
                  <>
                    <Button variant="miamiOutline" onClick={() => setStep('humanLibrarian')}>
                      Talk to a librarian
                    </Button>
                    <div className="text-center text-sm text-gray-700 py-1">
                      <Clock className="inline-block w-4 h-4 mr-1" />
                      <span>
                        We could not check whether a librarian is on chat
                        right now. Try the chat &mdash; if nobody is there,
                        create a ticket.
                      </span>
                    </div>
                  </>
                ) : askUsStatus.isOpen ? (
                  <Button variant="miamiOutline" onClick={() => setStep('humanLibrarian')}>
                    Talk to a librarian
                  </Button>
                ) : (
                  <div className="text-center text-sm text-gray-700 py-2">
                    {/* gray-500 measured 4.83:1 on white -- passes AA and
                        fails the 7:1 this widget is held to. */}
                    <Clock className="inline-block w-4 h-4 mr-1" />
                    {askUsStatus.nextOpen ? (
                      <span>
                        Librarian chat opens{' '}
                        {askUsStatus.nextOpen.when === 'later today'
                          ? ''
                          : `${askUsStatus.nextOpen.when} `}
                        at {askUsStatus.nextOpen.time}
                      </span>
                    ) : (
                      <span>Librarian chat is offline — create a ticket below</span>
                    )}
                  </div>
                )}
                
                <Button variant="miamiOutline" onClick={() => setStep('ticket')}>
                  Create a ticket
                </Button>
              </div>
            )}
            {/* A pause can land while someone is sitting on an open chat.
                They will never send another message, so the poll is the
                only thing that can tell them -- the notice goes above the
                transcript, which stays put, and the composer below it is
                disabled. Kept OUTSIDE the health ternary because a paused
                bot is healthy and connected; it is switched off, and
                "technical difficulties" would be a lie. */}
            {step === 'services' && isPaused && (
              <div className="mb-4">
                <OutOfServiceNotice askUsUrl={askUsUrl} compact />
              </div>
            )}
            {step === 'services' &&
              (serverStatus === 'healthy' && socketContextValues.isConnected ? (
                <ChatBotComponent askUsStatus={askUsStatus} isPaused={isPaused} />
              ) : (
                <div className="flex flex-col gap-4 text-center py-6">
                  <p className="text-red-500 font-bold">
                    Smart Chatbot is currently unavailable
                  </p>
                  <p className="text-gray-600 text-sm">
                    We're experiencing technical difficulties. 
                    {(askUsStatus.isOpen || !askUsStatus.known)
                      ? ' Let us connect you with a librarian.'
                      : ' Please submit a ticket and we\'ll get back to you.'}
                  </p>
                  {(askUsStatus.isOpen || !askUsStatus.known) ? (
                    <Button
                      variant="default"
                      onClick={() => setStep('humanLibrarian')}
                    >
                      Talk to a librarian
                    </Button>
                  ) : (
                    <Button
                      variant="default"
                      onClick={() => setStep('ticket')}
                    >
                      Submit a Ticket
                    </Button>
                  )}
                </div>
              ))}
            {step === 'humanLibrarian' && <HumanLibrarianWidget />}
            {step === 'ticket' && <OfflineTicketWidget />}
          </div>
          
          {/* Bottom action button during chat - shows librarian chat or ticket based on availability */}
          {step === 'services' && (
            <Button
              size="sm"
              variant="miamiOutline"
              className="fixed bottom-10 right-20 mr-4 absolute right-0 bottom-0 mb-2"
              onClick={() => (askUsStatus.isOpen || !askUsStatus.known)
                ? setStep('humanLibrarian') : setStep('ticket')}
            >
              {(askUsStatus.isOpen || !askUsStatus.known)
                ? 'Talk to a librarian' : 'Submit a ticket'}
            </Button>
          )}
        </DialogContent>
      </Dialog>
    </ErrorBoundaryComponent>
  );
};

export default App;
