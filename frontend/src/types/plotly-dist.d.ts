/**
 * `plotly.js-dist-min` ships no type declarations. The product talks to it
 * through `components/viz/plotly-chart.tsx` only, which types the narrow
 * surface it uses; everything else stays behind that one wrapper.
 */
declare module "plotly.js-dist-min" {
  const Plotly: {
    react: (el: HTMLElement, data: unknown[], layout: unknown, config?: unknown) => Promise<unknown>;
    purge: (el: HTMLElement) => void;
    downloadImage: (el: HTMLElement, opts: unknown) => Promise<string>;
    toImage: (el: HTMLElement, opts: unknown) => Promise<string>;
    Plots: { resize: (el: HTMLElement) => void };
  };
  export default Plotly;
}
