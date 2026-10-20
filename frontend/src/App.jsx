import React from 'react';
import Header from './components/Header';
import InspectionForm from './components/InspectionForm';

function App() {
  return (
    <div className="flex flex-col min-h-screen bg-field-light">
      <Header />

      {/* Main content */}
      <main className="flex-1 overflow-y-auto py-8">
        <div className="container mx-auto px-4 max-w-6xl">
          <InspectionForm />
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-200 py-4">
        <div className="container mx-auto px-6 text-center text-xs text-gray-600">
          <p>
            © {new Date().getFullYear()} Field Notes Studio.
            Audio and photo reports with human review.
          </p>
        </div>
      </footer>
    </div>
  );
}

export default App;
