// Line icons for the food groups (products.yaml keys), drawn on a 24 × 24 grid with one stroke
// width and round ends so they read as one set. Colour comes from the text (currentColor).

const PATHS = {
  // a plate between fork and knife
  all: `<circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="3"/><path d="M2.5 4v4a1 1 0 0 0 2 0V4M3.5 9v11M21.5 20V4c-1.6 1-2.2 3.2-2.2 6.5h2.2"/>`,
  // an ear of wheat
  cereals: `<path d="M12 21V9"/><path d="M12 13c-2.6 0-4.2-1.6-4.2-4.2 2.6 0 4.2 1.6 4.2 4.2zM12 13c2.6 0 4.2-1.6 4.2-4.2-2.6 0-4.2 1.6-4.2 4.2zM12 17.5c-2.6 0-4.2-1.6-4.2-4.2 2.6 0 4.2 1.6 4.2 4.2zM12 17.5c2.6 0 4.2-1.6 4.2-4.2-2.6 0-4.2 1.6-4.2 4.2zM12 8.6c-1.3-1.1-1.3-3.4 0-5.1 1.3 1.7 1.3 4 0 5.1z"/>`,
  // a potato with eyes
  potatoes_roots: `<path d="M4.2 12.8c-.9-3.6 2-6.6 5.6-7.3 2.2-.4 3.4.6 5.4.2 2.6-.5 5.3 1.3 4.9 4.6-.3 2.2-1.6 2.7-2.2 4.6-.9 2.8-3.2 4.3-6.4 4.1-3.4-.2-6.5-2.4-7.3-6.2z"/><path d="M9 11h.01M14.5 9.5h.01M12.5 15h.01"/>`,
  // three sugar cubes
  sugar: `<rect x="3.5" y="12" width="8" height="8" rx="1.5"/><rect x="12.5" y="12" width="8" height="8" rx="1.5"/><rect x="8" y="3.5" width="8" height="8" rx="1.5"/>`,
  // an open pea pod
  pulses: `<path d="M3.5 18.5C6 11 12 5.5 20.5 4c-.8 8.5-6.6 14.5-14 16.3-1.7.4-3.3-.4-3-1.8z"/><circle cx="8.6" cy="15.2" r="1.7"/><circle cx="12" cy="11.8" r="1.7"/><circle cx="15.4" cy="8.4" r="1.7"/>`,
  // a sunflower
  oilseeds: `<circle cx="12" cy="9" r="2"/><circle cx="16.0" cy="11.3" r="1.8"/><circle cx="12.0" cy="13.6" r="1.8"/><circle cx="8.0" cy="11.3" r="1.8"/><circle cx="8.0" cy="6.7" r="1.8"/><circle cx="12.0" cy="4.4" r="1.8"/><circle cx="16.0" cy="6.7" r="1.8"/><path d="M12 15.4V22M12 19.6c1.4-1.8 3.2-2.3 4.6-1.9-.8 1.6-2.6 2.3-4.6 1.9z"/>`,
  // a drop of oil
  vegetable_oils: `<path d="M12 3c3.2 4.3 6 7.7 6 11.2a6 6 0 0 1-12 0C6 10.7 8.8 7.3 12 3z"/><path d="M9.3 14.6a2.8 2.8 0 0 0 2.3 2.6"/>`,
  // a carrot with its leaves
  vegetables: `<path d="M15.8 8.2c-1.9-1.9-5-1.3-6.6.3L3.6 20.4l11.9-5.6c1.6-1.6 2.2-4.7.3-6.6z"/><path d="M15.8 8.2l3.4-3.4M15.8 8.2l.9-4.7M15.8 8.2l4.7-.9M9.6 12.6l1.6 1.6M7.4 16.4l1.1 1.1"/>`,
  // an apple with a leaf
  fruit: `<path d="M12 7.5c-1.6-1-5.2-1.4-6.6 1.6S5 16.3 7 18.8s3.6 2.6 5 1.6c1.4 1 3 .9 5-1.6s2-7.7.6-10.7S13.6 6.5 12 7.5z"/><path d="M12 7.5c0-2 .5-3.2 1.8-4.3"/><path d="M13 5.3c1.4-1.5 3.4-1.7 4.6-1.2-.5 1.6-2.5 2.6-4.6 1.2z"/>`,
  // a drumstick
  meat: `<path d="M14.6 3.6a5.8 5.8 0 0 1 5.8 5.8c0 3.6-3.4 6.2-6.8 5.6l-3.4 3.4a2.1 2.1 0 1 1-2.6 2.6 2.1 2.1 0 1 1-2.6-2.6 2.1 2.1 0 1 1 2.6-2.6l3.4-3.4c-.6-3.4 2-6.8 5.6-6.8z"/>`,
  // a milk carton
  dairy: `<path d="M8 3h8v3l2.5 3.5V21h-13V9.5L8 6z"/><path d="M8 6h8M5.5 9.5h13M10 14h4"/>`,
  // an egg
  eggs: `<path d="M12 3c-3.6 0-6.5 6-6.5 10.5a6.5 6.5 0 0 0 13 0C18.5 9 15.6 3 12 3z"/>`,
  // a fish
  fish: `<path d="M6.5 12c3-4 7.6-5.6 11-4.2 1.7.7 3 2.2 4 4.2-1 2-2.3 3.5-4 4.2-3.4 1.4-8-.2-11-4.2z"/><path d="M6.5 12 2.5 8v8z"/><path d="M17 11.2h.01"/>`,
  // a steaming cup
  stimulants: `<path d="M4 10h12v4.5A5.5 5.5 0 0 1 10.5 20h-1A5.5 5.5 0 0 1 4 14.5z"/><path d="M16 11h1.5a2.6 2.6 0 0 1 0 5.2H16"/><path d="M8 3.5c-.8.9-.8 2 0 3M12 3.5c-.8.9-.8 2 0 3"/>`,
  // a wine glass
  wine_beer: `<path d="M7.5 3h9l-.6 5.4a3.9 3.9 0 0 1-7.8 0z"/><path d="M7.9 6.5h8.2M12 12.3V20.5M8.5 20.5h7"/>`,
};

export function foodIcon(key) {
  const p = PATHS[key];
  return p
    ? `<svg class="ficon" viewBox="0 0 24 24" aria-hidden="true">${p}</svg>`
    : `<svg class="ficon" viewBox="0 0 24 24" aria-hidden="true"></svg>`;
}
