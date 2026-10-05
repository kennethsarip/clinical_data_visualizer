export default function App() {
  return (
    <main className="app">
      <header className="app-header">
        <h1>Trials Explorer</h1>
      </header>
      <section className="card">
        <div className="card-header">Ask a question</div>
        <div className="card-body">
          <textarea
            className="query-box"
            aria-label="Ask about clinical trials"
            placeholder="e.g. How has the number of pembrolizumab trials changed since 2015?"
          />
        </div>
      </section>
    </main>
  )
}
