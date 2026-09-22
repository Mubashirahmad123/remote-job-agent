/**
 * APP.JS — Application Orchestrator & Bootstrapper
 * Initializes all modular components cleanly on DOM ready.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Initialize Global Navigation & Shell
  if (JobAgent.navigation) JobAgent.navigation.init();

  // Initialize Dashboard Overview Widgets
  if (JobAgent.dashboard) JobAgent.dashboard.init();

  // Initialize Curated Jobs Desk & Filtering
  if (JobAgent.jobDesk) JobAgent.jobDesk.init();

  // Initialize Slide-Over Detail Drawer
  if (JobAgent.jobDrawer) JobAgent.jobDrawer.init();

  // Initialize CV Studio & 3-Pass ATS Generator
  if (JobAgent.resumeStudio) JobAgent.resumeStudio.init();

  // Initialize Auto-Apply Safety Cockpit
  if (JobAgent.autoApply) JobAgent.autoApply.init();

  // Initialize Application Kanban Tracker
  if (JobAgent.tracker) JobAgent.tracker.init();

  console.log('⚡ Remote Job Agent Command Center initialized successfully.');
});
