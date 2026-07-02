// =========================================
// FUNNEL EVENT TRACKING — BUBBL.OOO
// =========================================
// Fires GA4 + Meta Pixel events at key conversion points.
// Safe to call even if GA4/Pixel aren't loaded (checks before firing).

// --- UTM PERSISTENCE ---
// Save UTM params from URL to localStorage so they survive page navigation.
// These get picked up by the register page and sent to GA4 on sign_up.
(function() {
  const params = new URLSearchParams(window.location.search);
  const utmKeys = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'];
  utmKeys.forEach(function(key) {
    const val = params.get(key);
    if (val) localStorage.setItem(key, val);
  });
})();

const BubblAnalytics = {
  // --- GA4 Event ---
  ga(eventName, params = {}) {
    if (typeof gtag !== 'undefined') {
      gtag('event', eventName, params);
    }
  },

  // --- Meta Pixel Event ---
  fb(eventName, params = {}) {
    if (typeof fbq !== 'undefined') {
      fbq('track', eventName, params);
    }
  },

  // --- FUNNEL EVENTS ---

  // User registers (completes OTP verification)
  trackRegistration() {
    this.ga('sign_up', { method: 'email' });
    this.fb('CompleteRegistration');
  },

  // User creates a new chatbot
  trackBotCreated(botName) {
    this.ga('bot_created', { event_category: 'engagement', event_label: botName });
    this.fb('CustomizeProduct', { content_name: botName });
  },

  // User embeds the widget (visits integrate page)
  trackEmbed(botId) {
    this.ga('embed_widget', { event_category: 'engagement', event_label: 'bot_' + botId });
    this.fb('StartTrial', { content_name: 'embed_bot_' + botId });
  },

  // Lead captured by a bot
  trackLeadCaptured(botId) {
    this.ga('lead_captured', { event_category: 'conversion', event_label: 'bot_' + botId });
    this.fb('Lead', { content_name: 'bot_' + botId });
  },

  // User clicks a paid plan
  trackPlanClick(plan, value) {
    this.ga('plan_click', { event_category: 'monetization', event_label: plan, value: value });
    this.fb('InitiateCheckout', { content_name: plan, value: value, currency: 'INR' });
  },

  // User uploads a document
  trackDocUpload(botId) {
    this.ga('doc_uploaded', { event_category: 'engagement', event_label: 'bot_' + botId });
  },

  // User starts a scrape
  trackScrapeStarted(botId) {
    this.ga('scrape_started', { event_category: 'engagement', event_label: 'bot_' + botId });
  },

  // Contact form submitted
  trackContactForm() {
    this.ga('contact_form', { event_category: 'engagement' });
    this.fb('Contact');
  },

  // Waitlist signup
  trackWaitlist() {
    this.ga('waitlist_signup', { event_category: 'engagement' });
    this.fb('Subscribe');
  }
};
