// Landing page: what CCR is, who runs the platform, and the doors in -
// dashboard, guide, product/architecture. First-time visitors land here
// (localStorage flag); the header "About" link brings anyone back.

const STEPS = [
  {
    n: "1",
    title: "Upload your texts",
    body: "A CSV or Excel file with one text per row - tweets, essays, open-ended survey answers, transcripts.",
  },
  {
    n: "2",
    title: "Pick a validated scale",
    body: "Choose from the construct library (90+ published psychological scales) or paste your own questionnaire items.",
  },
  {
    n: "3",
    title: "Get scores you can defend",
    body: "Every text is scored against every item, with distributions, per-item loadings, warnings, and a downloadable script that reproduces the numbers on any machine.",
  },
];

export default function WelcomePage({ onEnter }) {
  return (
    <div className="welcome">
      <section className="welcome-hero card">
        <h2>Psychological text analysis, grounded in theory</h2>
        <p>
          The CCR Platform measures psychological constructs in text using{" "}
          <b>Contextualized Construct Representations</b> (CCR; Atari, Omrani,
          et&nbsp;al.) - instead of counting words or prompting a chatbot, it
          embeds <i>validated questionnaire items</i> and <i>your texts</i> with
          the same language model and scores each text by its similarity to the
          scale. Transparent, deterministic, and reproducible: the same input
          gives the same numbers, every time, and you can take the script home
          to prove it.
        </p>
        <div className="welcome-cta">
          <button className="primary" onClick={onEnter}>
            Open the dashboard →
          </button>
          <a className="ghost-link" href="/guide">How to use &amp; test it</a>
          <a className="ghost-link" href="/product">How it works under the hood</a>
        </div>
        <p className="hint">
          No account needed to try it - anonymous visitors get a few runs a day,
          and uploads are deleted right after their analysis. Accounts are free
          and keep your projects.
        </p>
      </section>

      <section className="welcome-steps">
        {STEPS.map((s) => (
          <div className="card welcome-step" key={s.n}>
            <div className="step-n">{s.n}</div>
            <h3>{s.title}</h3>
            <p className="hint">{s.body}</p>
          </div>
        ))}
      </section>

      <section className="card">
        <h3>Your data stays here</h3>
        <p className="hint">
          The embedding models run on this server - no text is ever sent to
          third-party AI APIs. Every run records the exact model version, scale
          wording, and package versions, so results are auditable and
          reproducible outside the platform.
        </p>
      </section>

      <section className="card">
        <h3>Who runs this</h3>
        <p className="hint">
          Built and maintained by the Culture &amp; Morality Lab (PI: Mohammad
          Atari) at the University of Massachusetts Amherst, building on the
          published CCR method and the lab's PsyEmbedding models. Questions,
          bugs, ideas: <a href="mailto:devaanand@umass.edu">devaanand@umass.edu</a>.
        </p>
      </section>
    </div>
  );
}
