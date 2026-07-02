"""Seed construct library — psychometrically validated scales.

IMPORTANT: item wordings below are seeded for demonstration. Before any
research use, verify each item verbatim against the cited original
publication (CCR's validity depends on using the validated instrument
as published).
"""

SEED_CONSTRUCTS = [
    {
        "name": "Satisfaction with Life",
        "description": "Global cognitive judgment of one's life satisfaction (SWLS).",
        "reference": "Diener, E., Emmons, R. A., Larsen, R. J., & Griffin, S. (1985). The Satisfaction with Life Scale. Journal of Personality Assessment, 49(1).",
        "items": [
            "In most ways my life is close to my ideal.",
            "The conditions of my life are excellent.",
            "I am satisfied with my life.",
            "So far I have gotten the important things I want in life.",
            "If I could live my life over, I would change almost nothing.",
        ],
    },
    {
        "name": "Moral Foundations — Care",
        "description": "Concern with suffering, compassion, and protection of the vulnerable (MFQ Care/Harm foundation).",
        "reference": "Graham, J., Nosek, B. A., Haidt, J., Iyer, R., Koleva, S., & Ditto, P. H. (2011). Mapping the moral domain. JPSP, 101(2). Verify items against the published MFQ.",
        "items": [
            "Compassion for those who are suffering is the most crucial virtue.",
            "One of the worst things a person could do is hurt a defenseless animal.",
            "Whether or not someone suffered emotionally.",
            "Whether or not someone cared for someone weak or vulnerable.",
        ],
    },
    {
        "name": "Moral Foundations — Fairness",
        "description": "Concern with justice, rights, and equal treatment (MFQ Fairness/Cheating foundation).",
        "reference": "Graham, J., Nosek, B. A., Haidt, J., Iyer, R., Koleva, S., & Ditto, P. H. (2011). Mapping the moral domain. JPSP, 101(2). Verify items against the published MFQ.",
        "items": [
            "Justice is the most important requirement for a society.",
            "When the government makes laws, the number one principle should be ensuring that everyone is treated fairly.",
            "Whether or not some people were treated differently than others.",
            "Whether or not someone acted unfairly.",
        ],
    },
    {
        "name": "Individualism (Horizontal)",
        "description": "Self-reliance and independence from in-groups (Triandis & Gelfand horizontal individualism).",
        "reference": "Triandis, H. C., & Gelfand, M. J. (1998). Converging measurement of horizontal and vertical individualism and collectivism. JPSP, 74(1). Verify items against the published scale.",
        "items": [
            "I'd rather depend on myself than others.",
            "I rely on myself most of the time; I rarely rely on others.",
            "I often do my own thing.",
            "My personal identity, independent of others, is very important to me.",
        ],
    },
    {
        "name": "Collectivism (Horizontal)",
        "description": "Interdependence, cooperation, and in-group well-being (Triandis & Gelfand horizontal collectivism).",
        "reference": "Triandis, H. C., & Gelfand, M. J. (1998). Converging measurement of horizontal and vertical individualism and collectivism. JPSP, 74(1). Verify items against the published scale.",
        "items": [
            "If a coworker gets a prize, I would feel proud.",
            "The well-being of my coworkers is important to me.",
            "To me, pleasure is spending time with others.",
            "I feel good when I cooperate with others.",
        ],
    },
]
