import ChatView from "./components/ChatView";

function App() {
  return (
    <main className="h-screen w-full overflow-hidden bg-slate-50 text-slate-900 transition-colors dark:bg-slate-950 dark:text-slate-100 antialiased">
      <ChatView />
    </main>
  );
}

export default App;