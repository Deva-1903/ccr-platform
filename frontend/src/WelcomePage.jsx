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
      {/* Hero copy is the PI's wording (2026-07-31) - edit only on request. */}
      <section className="welcome-hero card">
        <h2>Theory-Driven Psychological Text Analysis</h2>
        <p>
          <b>Contextualized Construct Representation (CCR)</b> offers a
          theory-driven way to measure psychological themes in text without
          relying on simple word counts. CCR uses validated questionnaire items
          (or prototypical statements) designed to assess psychological
          constructs such as individualism, moral values, depression,
          religiosity, or personality traits. A language model then compares
          the meaning of a passage with the meaning of each input sentence and
          produces a score indicating how strongly the passage reflects the
          construct of interest. CCR is free, open-source, publicly available,
          multilingual, adaptable to new language models, and highly flexible.
        </p>
        <div className="welcome-cta">
          <button className="primary" onClick={onEnter}>
            Open the dashboard →
          </button>
          {/* /product (architecture docs) is lab-internal now; the public
              landing only advertises the guide. Lab members reach it from
              the header. */}
          <a className="ghost-link" href="/guide">How to use &amp; test it</a>
        </div>
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
          This interface is designed, built, and maintained by the Culture &amp;
          Morality Lab (PI: Mohammad Atari) at the University of Massachusetts
          Amherst. The CCR pipeline is built based on Atari et al. (2023),
          extended and validated by Chen et al. (2024), and features
          PsyEmbedding language models, which are fine-tuned open-source models
          for psychological text analysis (Atari et al., 2026). For
          suggestions, questions, bugs, and ideas, reach out to the maintainer
          at <a href="mailto:devaanand@umass.edu">devaanand@umass.edu</a>.
        </p>
      </section>

      {/* Open-source disclaimer - the PI's wording verbatim (2026-07-31). */}
      <section className="card">
        <h3>Open-source disclaimer</h3>
        <p className="hint">
          This is an open-source software: use at your own risk. This
          open-source software is provided &quot;as is,&quot; without
          warranties or guarantees of accuracy, reliability, security, fitness
          for a particular purpose, or continued support. Users are
          responsible for validating outputs, protecting their data, and
          determining whether the software is appropriate for their intended
          use. The authors and contributors are not liable for losses or
          damages resulting from its use.
        </p>
      </section>
    </div>
  );
}
