import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import RouteStatus from './RouteStatus';

interface BoundaryProps {
  children: ReactNode;
}

interface BoundaryState {
  hasError: boolean;
}

class RouteErrorBoundaryImpl extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { hasError: false };

  static getDerivedStateFromError(): BoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    // Keep the diagnostic in the browser console for local debugging. The
    // rendered boundary intentionally exposes no stack or exception detail.
    console.error('Route rendering failed.', error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <RouteStatus
          status="error"
          title="This page could not be rendered."
          message="Refresh the page or return to the dashboard."
          onRetry={() => window.location.reload()}
          backTo="/"
          backLabel="Dashboard"
        />
      );
    }
    return this.props.children;
  }
}

/** Reset the page boundary when the routed location changes. */
const RouteErrorBoundary = ({ children }: BoundaryProps) => {
  const location = useLocation();
  const locationKey = `${location.pathname}${location.search}${location.hash}`;
  return (
    <RouteErrorBoundaryImpl key={locationKey}>
      {children}
    </RouteErrorBoundaryImpl>
  );
};

export default RouteErrorBoundary;
