import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium min-h-11 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        outline:
          "border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground",
        secondary:
          "bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
        // The DARK brand red for the same reason miamiOutline uses it:
        // #c41230 on white is 6.04:1, which passes AA and fails the 7:1
        // this widget is held to. #9e0f28 is 8.23:1 with white text.
        // Hover darkens with a filter rather than a lighter red, which
        // would have moved the contrast the wrong way.
        miami: "bg-miami-red-dark text-white shadow hover:brightness-90",
        // Red outline at rest, filled red on hover. The handoff buttons
        // ("Talk to a librarian", "Submit a ticket") were solid red, which
        // put them at the same visual weight as the primary action and
        // made the panel read as three competing red bars. A new variant
        // rather than an edit to `secondary`, which other surfaces use.
        //
        // The DARK brand red, not the bright one: #c41230 on white is
        // 6.04:1, which passes AA and fails the 7:1 this widget is held
        // to. #9e0f28 is 8.23:1 both ways -- red text on white at rest,
        // white text on red on hover -- and is already a brand token, so
        // nothing new was invented to get there.
        miamiOutline:
          "border border-miami-red-dark text-miami-red-dark bg-transparent " +
          "hover:bg-miami-red-dark hover:text-white " +
          "focus-visible:ring-miami-red-dark",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-8",
        xs: "h-7 rounded-md px-2 text-xs",
        icon: "h-9 w-9 min-w-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

const Button = React.forwardRef(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
