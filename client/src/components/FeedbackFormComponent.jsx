import { useContext, useState } from 'react';
import { Star } from 'lucide-react';
import { SocketContext } from '../context/SocketContextProvider';
import { MessageContext } from '../context/MessageContextProvider';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';

const FeedbackFormComponent = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [hover, setHover] = useState(null);
  const [rating, setRating] = useState(0);
  const [details, setDetails] = useState(undefined);
  const { socketContextValues } = useContext(SocketContext);
  const { messageContextValues } = useContext(MessageContext);

  const tooEarly = messageContextValues.message.length < 3;

  const handleFormOpen = () => {
    setIsOpen(true);
    setHover(null);
  };

  const handleRating = (curRating) => {
    setRating(curRating);
  };

  const handleFormSubmit = () => {
    socketContextValues.sendUserFeedback({
      userRating: rating,
      userComment: details,
    });
    setRating(0);
    setDetails(undefined);
    setHover(null);
    setIsOpen(false);
  };

  return (
    <>
      {/* Rating submits AND ends the session, so afterwards the chat is
          empty and this greys out again. That is right -- there is
          nothing to rate -- but a disabled control with no reason reads
          as broken, and the review reported exactly that: "deactivated
          after a rating even though it's a new chat". Say why.
          Reported in the accessibility review, 2026-08. */}
      <Button
        disabled={tooEarly}
        onClick={handleFormOpen}
        size="xs"
        variant="secondary"
        className="mr-[7%]"
        title={tooEarly ? 'Ask a question or two first, then you can rate the conversation' : undefined}
        aria-describedby={tooEarly ? 'rate-not-yet' : undefined}
      >
        Rate this conversation
      </Button>
      {tooEarly && (
        <span id="rate-not-yet" className="sr-only">
          Available once you have exchanged a few messages.
        </span>
      )}
      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent>
          <DialogHeader className="flex flex-row items-center ps-2">
            <img
              src="https://libapps.s3.amazonaws.com/accounts/190074/images/0721_STier1_Libraries_HS_186KW_K_Digital.png"
              height={50}
              width={120}
              alt="library logo"
            />
            <DialogTitle className="ml-3">Rate this conversation</DialogTitle>
          </DialogHeader>
          <form>
            <div className="space-y-4">
              <div>
                <Label>Rate this conversation</Label>
                {/* A radio whose only content is an icon has no accessible
                    name -- a screen reader announces "radio button" and
                    nothing else. Each one is named below, and the group is
                    named here. */}
                <div className="flex gap-0.5 mt-2" role="radiogroup" aria-label="Rate this answer, 1 to 5 stars">
                  {[...Array(5)].map((_, index) => {
                    const ratingValue = index + 1;
                    return (
                      /* Three things the accessibility review found here.
                         The radio is sr-only, so FOCUS was invisible --
                         a keyboard user could not see where they were.
                         yellow-400 on white is about 1.6:1, so a chosen
                         star and an unchosen one were hard to tell apart
                         at a glance, and gray-200 is barely visible at
                         all. And nothing but colour said which were
                         selected, which fails for anyone who cannot
                         separate those two colours. */
                      <label
                        key={index}
                        className="cursor-pointer p-0.5 rounded"
                        onMouseEnter={() => setHover(ratingValue)}
                        onMouseLeave={() => setHover(null)}
                      >
                        <input
                          type="radio"
                          name="rating"
                          aria-label={`${ratingValue} star${ratingValue === 1 ? '' : 's'}`}
                          checked={rating === ratingValue}
                          onChange={() => handleRating(ratingValue)}
                          value={ratingValue}
                          className="sr-only peer"
                        />
                        <Star
                          aria-hidden="true"
                          strokeWidth={2.25}
                          className={`h-6 w-6 transition-colors duration-200 rounded-sm
                            peer-focus-visible:outline peer-focus-visible:outline-2
                            peer-focus-visible:outline-offset-2
                            peer-focus-visible:outline-miami-red-dark ${
                            ratingValue <= (hover || rating)
                              ? /* amber-600 is 4.6:1 on white against
                                   yellow-400's 1.6, and the filled shape
                                   carries the state as well as the hue. */
                                'fill-amber-500 text-amber-600'
                              : /* Outline only, in a grey dark enough to
                                   see: shape distinguishes chosen from
                                   not, so colour is not doing it alone. */
                                'fill-none text-gray-500'
                          }`}
                        />
                      </label>
                    );
                  })}
                </div>
                {/* The chosen value in words. Colour alone told a sighted
                    reader; this tells everyone, and confirms the click
                    landed. aria-live so it is announced on change. */}
                <p className="mt-1 text-sm text-gray-700" aria-live="polite">
                  {rating
                    ? `${rating} of 5 stars selected`
                    : 'No rating selected yet'}
                </p>
              </div>
              <div>
                <Label htmlFor="feedback-details">Details</Label>
                <Textarea
          id="feedback-details"
                  placeholder="Enter details about your rating..."
                  value={details || ''}
                  onChange={(e) => setDetails(e.target.value)}
                  className="mt-2"
                />
              </div>
              <p className="text-red-500 text-sm italic">
                * Submitting this form will restart your session!
              </p>
            </div>
          </form>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setIsOpen(false)}>
              Close
            </Button>
            <Button variant="miami" onClick={handleFormSubmit}>
              Submit
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default FeedbackFormComponent;
