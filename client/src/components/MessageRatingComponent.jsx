import { useContext, useRef, useState } from 'react';
import { ThumbsUp, ThumbsDown } from 'lucide-react';
import { toast } from 'sonner';
import { SocketContext } from '../context/SocketContextProvider';
import { Button } from '@/components/ui/button';

const MessageRatingComponent = ({ message }) => {
  const [isDisabled, setIsDisabled] = useState(false);
  const isRated = useRef(false);
  const { socketContextValues } = useContext(SocketContext);

  const handleClick = (isPositiveRated) => {
    if (!isRated.current) {
      isRated.current = true;
      setIsDisabled(true);
      socketContextValues.sendMessageRating({
        messageId: message.messageId,
        isPositiveRated: isPositiveRated,
      });
      toast.success('Thank you for your feedback!', {
        description: 'We will use this information to improve user experience.',
        duration: 2000,
      });
    }
  };

  return (
    <div className="mt-1 flex gap-1">
      {/* An icon-only button with no text has no accessible name: a
          screen reader announces "button" and nothing else, twice in a
          row, and the reader cannot tell which is which. Reported in the
          accessibility review, 2026-08. */}
      <Button
        variant="ghost"
        size="sm"
        className="bg-gray-200 hover:bg-blue-400 hover:text-white"
        disabled={isDisabled}
        aria-label="This answer was helpful"
        onClick={() => handleClick(true)}
      >
        <ThumbsUp className="h-4 w-4" aria-hidden="true" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="bg-gray-200 hover:bg-red-400 hover:text-white"
        disabled={isDisabled}
        aria-label="This answer was not helpful"
        onClick={() => handleClick(false)}
      >
        <ThumbsDown className="h-4 w-4" aria-hidden="true" />
      </Button>
    </div>
  );
};

export default MessageRatingComponent;
