# Some notes might be helpful but just notes

## Springshare LibAnswers Ask Us Widget

HTML for offline view (Offline text 2)
```
<a href="{{ domain }}" target="_parent">
  Search our Knowledgebase and/or submit your question
</a>
<p></p>
<div class="mu-bot">
  <a class="mu-bot__cta" target="_blank" href="https://chatbot.lib.miamioh.edu/smartchatbot/">
    <span class="mu-bot__badge">BETA</span>Ask the Library Chatbot
  </a>
  <p class="mu-bot__scope">
    <strong>Try asking about</strong> hours, study spaces, borrowing, or who to contact.
  </p>
  <p class="mu-bot__note">This is a test version that helps you find information on the library website.</p>
</div>
```

CSS
```
.mu-bot {
  max-width: 360px;
  border-top: 1px solid #e6e6e2;
  margin-top: 16px;
  padding-top: 14px;
}

.mu-bot__cta {
  display: block;
  box-sizing: border-box;
  padding: 11px 14px;
  border: 1.5px solid #c3142d;
  border-radius: 6px;
  background: transparent;
  color: #c3142d;
  font-size: 15px;
  font-weight: 700;
  text-align: center;
  text-decoration: none;
  transition: background .15s ease, color .15s ease;
}

.mu-bot__cta:hover,
.mu-bot__cta:focus {
  background: #c3142d;
  color: #fff;
  text-decoration: none;
}

.mu-bot__cta:focus-visible {
  outline: 2px solid #185fa5;
  outline-offset: 2px;
}

.mu-bot__badge {
  display: inline-block;
  vertical-align: middle;
  margin-right: 8px;
  padding: 2px 7px;
  border-radius: 3px;
  background: #faeeda;
  color: #854f0b;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: .08em;
  animation: mu-beta-pulse 1.8s ease-in-out infinite;
}

@keyframes mu-beta-pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: .45;
  }
.mu-bot__scope {
  margin: 10px 0 0;
  font-size: 13px;
  line-height: 1.5;
  color: #5f5e5a;
}

.mu-bot__scope strong {
  font-weight: 700;
  color: #2c2c2a;
}

.mu-bot__note {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: #888780;
}

@media (prefers-reduced-motion: reduce) {
  .mu-bot__badge {
    animation: none;
  }
}

```