"""
Stage 5: Synthetic Brand Guidelines Dataset Generator
Output: datasets/processed/brand_guidelines/
  - brand_identity.json
  - tone_voice_per_persona.json
  - channel_templates.json
  - cta_library.json
  - localization_rules.json
  - compliance_rules.json
  - brand_guidelines_full.txt   ← merged document for RAG chunking & embedding
"""

import json
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).resolve().parent.parent
OUT_DIR  = ROOT / "datasets" / "processed" / "brand_guidelines"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# 1. BRAND IDENTITY
# ══════════════════════════════════════════════════════════════════════════════
brand_identity = {
    "brand_name": "Omnibrand Studio",
    "tagline": "Elevate the Everyday",
    "industry": "Lifestyle & Consumer Goods",
    "founded": 2010,
    "mission": (
        "To enrich everyday living by delivering curated, high-quality products "
        "across food, fashion, home, health, and technology — tailored to every "
        "lifestyle and budget."
    ),
    "vision": (
        "To be the most trusted lifestyle brand globally, where every customer "
        "feels seen, valued, and inspired regardless of their spending power."
    ),
    "core_values": [
        "Quality — Every product and piece of content must meet a high standard.",
        "Trust — We never overpromise. Every claim must be accurate and verifiable.",
        "Inclusivity — We speak to all customer segments with equal respect.",
        "Innovation — We embrace technology and creativity in everything we do.",
        "Sustainability — We promote mindful consumption and responsible choices."
    ],
    "brand_personality": [
        "Warm but professional",
        "Inspiring without being pushy",
        "Knowledgeable but never condescending",
        "Confident but approachable"
    ],
    "product_categories": [
        "Food & Beverages (Wines, Gourmet Foods, Sweets)",
        "Fashion & Accessories",
        "Home & Living",
        "Health & Wellness",
        "Technology & Gadgets"
    ],
    "primary_markets": ["United States", "France", "Spain", "United Kingdom"],
    "primary_languages": ["English", "French", "Spanish"],
    "brand_colors": {
        "primary": "#1A1A2E",
        "secondary": "#E94560",
        "accent": "#F5A623",
        "neutral": "#F7F7F7"
    },
    "brand_fonts": {
        "heading": "Playfair Display",
        "body": "Inter",
        "accent": "Montserrat"
    }
}

# ══════════════════════════════════════════════════════════════════════════════
# 2. TONE & VOICE PER PERSONA
# ══════════════════════════════════════════════════════════════════════════════
tone_voice_per_persona = {
    "High-Income Store Spender": {
        "description": "Wealthy, educated customers who shop in-store and spend heavily across all categories.",
        "tone": "Premium, sophisticated, exclusive, confident",
        "language_style": "Elevated vocabulary, longer sentences, no slang, subtle elegance",
        "emotional_appeal": "Aspiration, exclusivity, quality craftsmanship, status",
        "key_messages": [
            "You deserve the finest — and we deliver it.",
            "Exclusively curated for discerning tastes.",
            "Quality that speaks for itself.",
            "A world of premium products, personally selected for you."
        ],
        "content_focus": [
            "Highlight premium product quality and provenance",
            "Emphasise exclusivity and limited availability",
            "Reference craftsmanship, heritage, and expertise",
            "Use lifestyle imagery that reflects luxury and refinement"
        ],
        "avoid": [
            "Discount language (e.g. 'cheap', 'bargain', 'save big')",
            "Overly casual or informal tone",
            "Hard-sell urgency tactics",
            "Generic mass-market messaging"
        ],
        "sentence_length": "Medium to long",
        "preferred_channels": ["Store", "Catalog", "Email"],
        "campaign_approach": "Multi-touchpoint storytelling journey — build desire before presenting product"
    },
    "Budget-Conscious Low Spender": {
        "description": "Price-sensitive customers who spend minimally and rarely respond to campaigns.",
        "tone": "Reassuring, honest, helpful, straightforward",
        "language_style": "Simple vocabulary, short sentences, plain and clear, no jargon",
        "emotional_appeal": "Security, practicality, value for money, trust",
        "key_messages": [
            "Great quality doesn't have to cost more.",
            "Smart choices for everyday living.",
            "We respect your budget — and your intelligence.",
            "Real value, real savings, real results."
        ],
        "content_focus": [
            "Lead with price and value proposition",
            "Highlight savings and affordability clearly",
            "Use simple, relatable everyday scenarios",
            "Focus on practical benefits over aspirational lifestyle"
        ],
        "avoid": [
            "Premium or luxury language",
            "Complicated or abstract messaging",
            "High-pressure sales tactics",
            "Imagery or language that feels out of reach"
        ],
        "sentence_length": "Short to medium",
        "preferred_channels": ["Store", "Deals", "Email"],
        "campaign_approach": "Reactivation campaigns with clear value offers — keep messaging simple and honest"
    },
    "Web-Savvy Mid-Tier Buyer": {
        "description": "Mid-income customers who prefer online shopping and are comfortable with digital content.",
        "tone": "Modern, friendly, snappy, digitally native",
        "language_style": "Conversational, punchy, uses digital-native expressions, emoji-friendly",
        "emotional_appeal": "Convenience, discovery, smart choices, staying current",
        "key_messages": [
            "Shop smarter. Live better.",
            "Everything you need, right here, right now.",
            "Discover what's trending — curated just for you.",
            "Fast. Easy. Delivered to your door."
        ],
        "content_focus": [
            "Emphasise convenience and seamless online experience",
            "Highlight new arrivals, trending products, and personalised picks",
            "Use short punchy copy with strong visual support",
            "Include social proof — ratings, reviews, popular picks"
        ],
        "avoid": [
            "Long-form text blocks",
            "Offline-only references (e.g. 'visit us in-store')",
            "Overly formal or stiff language",
            "Outdated references or out-of-touch cultural references"
        ],
        "sentence_length": "Short",
        "preferred_channels": ["Web", "Instagram", "Facebook", "Email"],
        "campaign_approach": "Digital-first campaigns with retargeting — use web behaviour signals to personalise"
    },
    "Deal-Seeking Value Hunter": {
        "description": "Low-income customers who only engage when there is a compelling deal or discount.",
        "tone": "Urgent, direct, deal-driven, energetic",
        "language_style": "Short punchy sentences, numbers and percentages prominent, action-oriented",
        "emotional_appeal": "FOMO (fear of missing out), urgency, winning a deal, smart shopping",
        "key_messages": [
            "Today only — don't miss out.",
            "Your exclusive deal is waiting.",
            "Up to 50% off. Right now.",
            "Act fast — limited stock at this price."
        ],
        "content_focus": [
            "Lead with the discount or offer — make it the headline",
            "Include specific numbers (%, $ saved, items remaining)",
            "Use countdown language and limited-time framing",
            "Keep copy minimal — let the offer speak"
        ],
        "avoid": [
            "Soft or ambiguous offers",
            "Long explanations before revealing the deal",
            "Premium positioning or luxury language",
            "Vague CTAs like 'Learn More'"
        ],
        "sentence_length": "Very short",
        "preferred_channels": ["Deals", "Email", "Facebook"],
        "campaign_approach": "Trigger-based campaigns tied to promotions — only contact when there is a genuine deal"
    },
    "Highly Engaged Campaign Responder": {
        "description": "The rarest and most responsive segment — actively responds to campaigns across touchpoints.",
        "tone": "Loyal, rewarding, inclusive, celebratory",
        "language_style": "Warm and personal, uses 'you' frequently, acknowledges their loyalty",
        "emotional_appeal": "Recognition, belonging, reward, being valued",
        "key_messages": [
            "You've been with us from the start — here's something special.",
            "As one of our most valued customers, this is for you.",
            "Thank you for your loyalty. You deserve this.",
            "Exclusively for our most engaged community members."
        ],
        "content_focus": [
            "Acknowledge and reward their engagement history",
            "Offer early access, exclusives, or loyalty rewards",
            "Use personalised language that references their behaviour",
            "Build on the relationship — reference previous campaigns"
        ],
        "avoid": [
            "Generic mass-market messaging",
            "Ignoring their loyalty history",
            "Treating them like a new customer",
            "Overly transactional tone"
        ],
        "sentence_length": "Medium",
        "preferred_channels": ["Catalog", "Email", "Store"],
        "campaign_approach": "Loyalty-first campaigns — reward before asking. Use full 6-step campaign sequences."
    }
}

# ══════════════════════════════════════════════════════════════════════════════
# 3. CHANNEL TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════
channel_templates = {
    "Email": {
        "max_subject_line_length": 50,
        "max_preview_text_length": 100,
        "max_body_length": 300,
        "structure": ["Subject Line", "Preview Text", "Greeting", "Body (1-2 paragraphs)", "CTA Button", "Footer"],
        "tone_guidance": "Personal, direct, one clear message per email",
        "formatting_rules": [
            "One primary CTA per email — never two competing actions",
            "Subject line must not exceed 50 characters",
            "Avoid all caps in subject lines",
            "Personalise with first name where possible",
            "Mobile-optimised — assume 60% of opens are on mobile"
        ],
        "do": ["Use numbered or bulleted lists for product features", "Include unsubscribe link", "Test subject line A/B"],
        "do_not": ["Use spam trigger words (free, guaranteed, winner)", "Attach files", "Use more than 2 images"],
        "example_structure": {
            "subject": "[First Name], your exclusive offer is here",
            "preview": "Specially selected for you — available today only",
            "greeting": "Hi [First Name],",
            "body": "[1-2 sentences on product/offer]. [1 sentence on why it's relevant to them].",
            "cta": "Shop Now",
            "footer": "Omnibrand Studio | Unsubscribe | Privacy Policy"
        }
    },
    "Instagram": {
        "max_caption_length": 150,
        "max_hashtags": 5,
        "structure": ["Hook (first line)", "Body", "CTA", "Hashtags"],
        "tone_guidance": "Visual-first, punchy, aspirational, community-driven",
        "formatting_rules": [
            "First line must be a hook — it appears before 'more'",
            "Keep caption under 150 characters for best engagement",
            "Use 3-5 relevant hashtags — never more than 5",
            "Emojis allowed — use sparingly (max 3 per post)",
            "Always include one clear CTA"
        ],
        "do": ["Use high-quality lifestyle imagery", "Tag products", "Use Stories for flash deals"],
        "do_not": ["Use long paragraphs", "Use more than 5 hashtags", "Post blurry or low-res images"],
        "example_structure": {
            "hook": "Your new favourite just arrived. ✨",
            "body": "Discover [product] — crafted for [persona need].",
            "cta": "Shop the link in bio.",
            "hashtags": "#Omnibrand Studio #ElevateTheEveryday #[Category]"
        }
    },
    "Facebook": {
        "max_post_length": 250,
        "structure": ["Opening Statement", "Body", "CTA", "Link Preview"],
        "tone_guidance": "Conversational, community-oriented, slightly longer than Instagram",
        "formatting_rules": [
            "Keep posts under 250 characters for best organic reach",
            "Use line breaks to improve readability",
            "Include a link for retargeting",
            "Emojis allowed but professional context only",
            "Sponsored posts must include 'Sponsored' disclosure"
        ],
        "do": ["Use video content for higher reach", "Respond to comments within 24 hours", "Use carousel format for multiple products"],
        "do_not": ["Post without an image or video", "Use clickbait headlines", "Over-post (max 1x per day)"],
        "example_structure": {
            "opening": "Looking for [benefit]? We've got you covered.",
            "body": "[Product] is here — [key benefit in one sentence]. [Social proof or offer].",
            "cta": "Shop now → [link]"
        }
    },
    "LinkedIn": {
        "max_post_length": 400,
        "structure": ["Professional Hook", "Value Statement", "Product/Offer Context", "CTA"],
        "tone_guidance": "Professional, thought-leadership, B2B-friendly where relevant",
        "formatting_rules": [
            "Lead with a professional insight or statistic",
            "Avoid overly casual language",
            "Use line breaks generously for readability",
            "No more than 3 hashtags",
            "Focus on business value and ROI language"
        ],
        "do": ["Tag relevant industry accounts", "Share data and insights", "Use native documents or carousels"],
        "do_not": ["Use slang or emojis excessively", "Hard-sell in first paragraph", "Repost Instagram content verbatim"],
        "example_structure": {
            "hook": "The way [industry] approaches [topic] is changing.",
            "value": "At Omnibrand Studio, we believe [core value statement].",
            "context": "[Product/service] helps [target] achieve [outcome].",
            "cta": "Learn more: [link]"
        }
    },
    "Web": {
        "max_headline_length": 60,
        "max_subheadline_length": 100,
        "max_body_length": 200,
        "structure": ["Headline", "Subheadline", "Body Copy", "Primary CTA", "Secondary CTA (optional)"],
        "tone_guidance": "Clear, benefit-led, SEO-aware, scannable",
        "formatting_rules": [
            "Headline must communicate the core benefit in under 60 characters",
            "Use active voice throughout",
            "Body copy should be scannable — short paragraphs, bullet points",
            "Primary CTA must be above the fold",
            "Avoid jargon — write for a general audience"
        ],
        "do": ["Use customer testimonials", "Include trust signals (ratings, reviews)", "A/B test CTA button copy"],
        "do_not": ["Use passive voice", "Bury the CTA below the fold", "Use stock imagery that looks generic"],
        "example_structure": {
            "headline": "[Benefit] — [Short Differentiator]",
            "subheadline": "Discover [product] designed for [persona need].",
            "body": "[1-2 sentences on product value]. [1 sentence on offer or proof].",
            "primary_cta": "Shop Now",
            "secondary_cta": "Learn More"
        }
    },
    "Catalog": {
        "max_product_description_length": 80,
        "max_feature_bullets": 4,
        "structure": ["Product Name", "Short Description", "Feature Bullets", "Price", "CTA"],
        "tone_guidance": "Precise, informative, benefit-led, premium feel",
        "formatting_rules": [
            "Product description must be under 80 words",
            "Maximum 4 bullet points per product",
            "Always include price prominently",
            "Use high-resolution product photography",
            "Consistent formatting across all product entries"
        ],
        "do": ["Group products by category", "Include product codes", "Add 'Best Seller' or 'New' badges"],
        "do_not": ["Use vague descriptions", "Omit pricing", "Mix formatting styles across products"],
        "example_structure": {
            "product_name": "[Product Name] — [Variant]",
            "description": "[One sentence on what it is and its primary benefit].",
            "bullets": ["[Feature 1]", "[Feature 2]", "[Feature 3]", "[Feature 4]"],
            "price": "$[XX.XX]",
            "cta": "Order Now | Product Code: [XXX]"
        }
    }
}

# ══════════════════════════════════════════════════════════════════════════════
# 4. CTA LIBRARY
# ══════════════════════════════════════════════════════════════════════════════
cta_library = {
    "High-Income Store Spender": {
        "primary_ctas": [
            "Explore the Collection",
            "Discover Your Selection",
            "View Exclusive Pieces",
            "Reserve Yours Today",
            "Shop the Edit"
        ],
        "urgency_level": "Low — exclusivity over urgency",
        "tone": "Invitation, not pressure",
        "channel_specific": {
            "Email": "Explore the Collection",
            "Instagram": "Shop the Edit",
            "Facebook": "Discover More",
            "Web": "View Exclusive Pieces",
            "Catalog": "Reserve Yours Today",
            "Store": "Visit Us In-Store"
        }
    },
    "Budget-Conscious Low Spender": {
        "primary_ctas": [
            "See Today's Deals",
            "Find Your Savings",
            "Shop Smart",
            "View Best Value Picks",
            "Get Yours Now"
        ],
        "urgency_level": "Medium — value-focused",
        "tone": "Helpful and reassuring",
        "channel_specific": {
            "Email": "See Your Savings",
            "Instagram": "Shop Smart",
            "Facebook": "Find Best Value",
            "Web": "View Best Value Picks",
            "Catalog": "Order at Best Price",
            "Store": "Find In-Store Deals"
        }
    },
    "Web-Savvy Mid-Tier Buyer": {
        "primary_ctas": [
            "Shop Now",
            "Add to Cart",
            "Get It Today",
            "See What's New",
            "Start Shopping"
        ],
        "urgency_level": "Medium — convenience-focused",
        "tone": "Snappy and action-driven",
        "channel_specific": {
            "Email": "Shop Now",
            "Instagram": "Link in Bio",
            "Facebook": "Shop Now",
            "Web": "Add to Cart",
            "Catalog": "Order Online",
            "Store": "Find In-Store"
        }
    },
    "Deal-Seeking Value Hunter": {
        "primary_ctas": [
            "Grab This Deal",
            "Claim Your Discount",
            "Shop Before It's Gone",
            "Get [X]% Off Now",
            "Unlock Your Offer"
        ],
        "urgency_level": "High — time and scarcity driven",
        "tone": "Urgent and direct",
        "channel_specific": {
            "Email": "Claim Your Discount",
            "Instagram": "Grab the Deal",
            "Facebook": "Shop Before It's Gone",
            "Web": "Unlock Your Offer",
            "Catalog": "Order at Sale Price",
            "Store": "Show This Offer In-Store"
        }
    },
    "Highly Engaged Campaign Responder": {
        "primary_ctas": [
            "Claim Your Reward",
            "Access Your Exclusive Offer",
            "Thank You — Shop Now",
            "Your Early Access Starts Here",
            "See What We've Saved for You"
        ],
        "urgency_level": "Medium — loyalty and reward driven",
        "tone": "Personal and appreciative",
        "channel_specific": {
            "Email": "Claim Your Reward",
            "Instagram": "Early Access — Link in Bio",
            "Facebook": "Access Your Exclusive Offer",
            "Web": "See What We've Saved for You",
            "Catalog": "Your Loyalty Offer Inside",
            "Store": "Show This for Your Reward"
        }
    }
}

# ══════════════════════════════════════════════════════════════════════════════
# 5. LOCALIZATION RULES
# ══════════════════════════════════════════════════════════════════════════════
localization_rules = {
    "English": {
        "region": "United States, United Kingdom",
        "formality_level": "Neutral — adapts to persona tone",
        "date_format": "MM/DD/YYYY (US) | DD/MM/YYYY (UK)",
        "currency": "USD ($) | GBP (£)",
        "cultural_notes": [
            "Direct communication is appreciated — get to the point",
            "Humour is acceptable but must be subtle and brand-safe",
            "Avoid British vs American English conflicts — use internationally neutral terms where possible",
            "Spelling: use 'color' not 'colour' for US, 'colour' not 'color' for UK"
        ],
        "phrases_to_avoid": [
            "Bloody good deal (UK slang — not brand appropriate)",
            "Ya'll (too regional for brand voice)",
            "Awesome sauce (too informal for all personas)"
        ],
        "legal_disclaimers": [
            "Prices subject to change without notice.",
            "Offer valid while supplies last.",
            "See website for full terms and conditions."
        ]
    },
    "French": {
        "region": "France, Belgium, Canada (Quebec)",
        "formality_level": "High — French audiences expect formal register by default",
        "date_format": "DD/MM/YYYY",
        "currency": "EUR (€) | CAD ($) for Quebec",
        "cultural_notes": [
            "Always use 'vous' (formal you) unless specifically targeting Gen Z on social media",
            "French consumers value quality and elegance over bargain language",
            "Avoid direct translations of English idioms — they often read as unnatural",
            "Food and lifestyle content resonates strongly with French audiences",
            "Brand messaging must feel crafted — rushed or generic copy is poorly received"
        ],
        "phrases_to_avoid": [
            "Direct translations of English slang",
            "Overly enthusiastic exclamation marks (seen as tacky in French)",
            "'Super' used excessively (informal and overused)",
            "RSVP in reverse — do not use English idioms untranslated"
        ],
        "legal_disclaimers": [
            "Prix susceptibles de modification sans préavis.",
            "Offre valable dans la limite des stocks disponibles.",
            "Voir le site pour les conditions générales complètes."
        ]
    },
    "Spanish": {
        "region": "Spain, Mexico, United States (Hispanic market)",
        "formality_level": "Medium — warm and personal, less formal than French",
        "date_format": "DD/MM/YYYY",
        "currency": "EUR (€) for Spain | MXN ($) for Mexico | USD ($) for US Hispanic",
        "cultural_notes": [
            "Use 'usted' for formal contexts, 'tú' for social media and younger audiences",
            "Family and community values resonate strongly — reference shared experiences",
            "Colour and warmth in language is culturally appropriate — Spanish audiences respond to emotive copy",
            "Distinguish between Spain Spanish and Latin American Spanish where possible",
            "Health and food content performs especially well in Spanish-language campaigns"
        ],
        "phrases_to_avoid": [
            "Direct word-for-word translations from English",
            "Slang specific to one Spanish-speaking country used globally",
            "Overly corporate or cold language — warmth is expected"
        ],
        "legal_disclaimers": [
            "Precios sujetos a cambio sin previo aviso.",
            "Oferta válida hasta agotar existencias.",
            "Consulte el sitio web para conocer los términos y condiciones completos."
        ]
    }
}

# ══════════════════════════════════════════════════════════════════════════════
# 6. COMPLIANCE & BRAND SAFETY RULES
# ══════════════════════════════════════════════════════════════════════════════
compliance_rules = {
    "absolute_prohibitions": [
        "Never make unverified health claims (e.g. 'cures', 'prevents disease')",
        "Never guarantee financial returns or investment outcomes",
        "Never use competitor brand names in comparative claims without legal approval",
        "Never use customer data references in content (e.g. 'we know you bought X')",
        "Never create content that discriminates based on age, gender, race, religion, or disability",
        "Never use images of minors in commercial advertising without explicit consent documentation",
        "Never claim 'best' or '#1' without a cited, verified source",
        "Never make environmental claims (e.g. 'eco-friendly', 'carbon neutral') without certification"
    ],
    "prohibited_words_and_phrases": [
        "Guaranteed", "100% proven", "Risk-free", "No side effects",
        "Miracle", "Secret formula", "Limited to first 10 only (without verification)",
        "Free (when conditions apply without disclosure)", "Clinically proven (without citation)"
    ],
    "required_disclosures": [
        "All sponsored content must include 'Sponsored' or 'Ad' label",
        "Affiliate links must be disclosed with #ad or #sponsored",
        "Testimonials must reflect genuine customer experience",
        "Before/after imagery requires disclaimer: 'Results may vary'",
        "Sale prices must reference original price with evidence"
    ],
    "ai_content_guardrails": [
        "All AI-generated content must be reviewed for factual accuracy before publishing",
        "AI must not invent product specifications, prices, or availability",
        "AI must not fabricate customer testimonials or reviews",
        "AI-generated content must stay within the approved tone for the assigned persona",
        "AI must not generate content that contradicts established brand values",
        "All CTAs generated by AI must come from the approved CTA library",
        "AI must flag any claim that requires legal or compliance verification"
    ],
    "content_review_process": [
        "Stage 1 — AI generates draft content based on persona and channel template",
        "Stage 2 — Automated brand guardrail check against compliance rules",
        "Stage 3 — Human review for factual accuracy and legal compliance",
        "Stage 4 — Final approval before publishing"
    ],
    "sensitive_topics": [
        "Politics — never take a political stance",
        "Religion — avoid religious references in commercial content",
        "Personal finance — do not give financial advice",
        "Medical advice — do not give health or medical recommendations",
        "Alcohol — follow platform-specific age-gating rules for wine/beverage content"
    ]
}

# ══════════════════════════════════════════════════════════════════════════════
# SAVE ALL JSON FILES
# ══════════════════════════════════════════════════════════════════════════════
files = {
    "brand_identity.json":        brand_identity,
    "tone_voice_per_persona.json": tone_voice_per_persona,
    "channel_templates.json":     channel_templates,
    "cta_library.json":           cta_library,
    "localization_rules.json":    localization_rules,
    "compliance_rules.json":      compliance_rules,
}

print("=" * 60)
print("SAVING JSON FILES")
print("=" * 60)
for filename, data in files.items():
    path = OUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved → {path}")

# ══════════════════════════════════════════════════════════════════════════════
# GENERATE MERGED TEXT DOCUMENT FOR RAG EMBEDDING
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("GENERATING MERGED RAG DOCUMENT")
print("=" * 60)

def section(title):
    return f"\n{'=' * 60}\n{title}\n{'=' * 60}\n"

def subsection(title):
    return f"\n--- {title} ---\n"

lines = []
lines.append("LUMINARY BRAND GUIDELINES — FULL REFERENCE DOCUMENT")
lines.append("Generated for RAG Embedding | AI Content Supply Chain Platform")
lines.append("=" * 60)

# ── Section 1: Brand Identity ─────────────────────────────────────────────────
lines.append(section("1. BRAND IDENTITY"))
lines.append(f"Brand Name    : {brand_identity['brand_name']}")
lines.append(f"Tagline       : {brand_identity['tagline']}")
lines.append(f"Industry      : {brand_identity['industry']}")
lines.append(f"Mission       : {brand_identity['mission']}")
lines.append(f"Vision        : {brand_identity['vision']}")
lines.append("\nCore Values:")
for v in brand_identity["core_values"]:
    lines.append(f"  - {v}")
lines.append("\nBrand Personality:")
for p in brand_identity["brand_personality"]:
    lines.append(f"  - {p}")
lines.append("\nProduct Categories:")
for c in brand_identity["product_categories"]:
    lines.append(f"  - {c}")
lines.append(f"\nPrimary Languages: {', '.join(brand_identity['primary_languages'])}")
lines.append(f"Primary Markets  : {', '.join(brand_identity['primary_markets'])}")

# ── Section 2: Tone & Voice Per Persona ──────────────────────────────────────
lines.append(section("2. TONE & VOICE PER PERSONA"))
for persona, rules in tone_voice_per_persona.items():
    lines.append(subsection(persona))
    lines.append(f"Description    : {rules['description']}")
    lines.append(f"Tone           : {rules['tone']}")
    lines.append(f"Language Style : {rules['language_style']}")
    lines.append(f"Emotional Appeal: {rules['emotional_appeal']}")
    lines.append(f"Sentence Length: {rules['sentence_length']}")
    lines.append(f"Preferred Channels: {', '.join(rules['preferred_channels'])}")
    lines.append(f"Campaign Approach : {rules['campaign_approach']}")
    lines.append("\nKey Messages:")
    for m in rules["key_messages"]:
        lines.append(f"  - {m}")
    lines.append("\nContent Focus:")
    for f in rules["content_focus"]:
        lines.append(f"  - {f}")
    lines.append("\nAvoid:")
    for a in rules["avoid"]:
        lines.append(f"  - {a}")

# ── Section 3: Channel Templates ─────────────────────────────────────────────
lines.append(section("3. CHANNEL TEMPLATES"))
for channel, rules in channel_templates.items():
    lines.append(subsection(channel))
    lines.append(f"Tone Guidance  : {rules['tone_guidance']}")
    lines.append(f"Structure      : {' → '.join(rules['structure'])}")
    lines.append("\nFormatting Rules:")
    for r in rules["formatting_rules"]:
        lines.append(f"  - {r}")
    lines.append("\nDo:")
    for d in rules["do"]:
        lines.append(f"  + {d}")
    lines.append("\nDo Not:")
    for d in rules["do_not"]:
        lines.append(f"  x {d}")

# ── Section 4: CTA Library ───────────────────────────────────────────────────
lines.append(section("4. CTA LIBRARY"))
for persona, ctas in cta_library.items():
    lines.append(subsection(persona))
    lines.append(f"Urgency Level  : {ctas['urgency_level']}")
    lines.append(f"Tone           : {ctas['tone']}")
    lines.append("\nApproved CTAs:")
    for c in ctas["primary_ctas"]:
        lines.append(f"  - {c}")
    lines.append("\nChannel-Specific CTAs:")
    for ch, cta in ctas["channel_specific"].items():
        lines.append(f"  {ch:<12}: {cta}")

# ── Section 5: Localization Rules ────────────────────────────────────────────
lines.append(section("5. LOCALIZATION RULES"))
for lang, rules in localization_rules.items():
    lines.append(subsection(lang))
    lines.append(f"Region         : {rules['region']}")
    lines.append(f"Formality      : {rules['formality_level']}")
    lines.append(f"Date Format    : {rules['date_format']}")
    lines.append(f"Currency       : {rules['currency']}")
    lines.append("\nCultural Notes:")
    for n in rules["cultural_notes"]:
        lines.append(f"  - {n}")
    lines.append("\nPhrases to Avoid:")
    for p in rules["phrases_to_avoid"]:
        lines.append(f"  x {p}")
    lines.append("\nLegal Disclaimers:")
    for d in rules["legal_disclaimers"]:
        lines.append(f"  * {d}")

# ── Section 6: Compliance Rules ──────────────────────────────────────────────
lines.append(section("6. COMPLIANCE & BRAND SAFETY RULES"))
lines.append(subsection("Absolute Prohibitions"))
for r in compliance_rules["absolute_prohibitions"]:
    lines.append(f"  x {r}")
lines.append(subsection("Prohibited Words and Phrases"))
for w in compliance_rules["prohibited_words_and_phrases"]:
    lines.append(f"  x {w}")
lines.append(subsection("Required Disclosures"))
for d in compliance_rules["required_disclosures"]:
    lines.append(f"  * {d}")
lines.append(subsection("AI Content Guardrails"))
for g in compliance_rules["ai_content_guardrails"]:
    lines.append(f"  - {g}")
lines.append(subsection("Content Review Process"))
for s in compliance_rules["content_review_process"]:
    lines.append(f"  - {s}")
lines.append(subsection("Sensitive Topics"))
for t in compliance_rules["sensitive_topics"]:
    lines.append(f"  - {t}")

# ── Write merged document ─────────────────────────────────────────────────────
full_text_path = OUT_DIR / "brand_guidelines_full.txt"
with open(full_text_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Merged RAG document saved → {full_text_path}")
print(f"Total lines in document   : {len(lines)}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"Output directory : {OUT_DIR}")
print(f"Files generated  : {len(files) + 1}")
for filename in list(files.keys()) + ["brand_guidelines_full.txt"]:
    path = OUT_DIR / filename
    size_kb = path.stat().st_size / 1024
    print(f"  {filename:<40} {size_kb:.1f} KB")
