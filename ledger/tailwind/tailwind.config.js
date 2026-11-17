/** Tailwind is compiled ahead of time into static/app.css. Rebuild with
 *  ./tailwind/build.sh after changing templates/ or static/app.js. */
const tone = (name) => `rgb(var(--${name}) / <alpha-value>)`;
module.exports = {
  content: ["./templates/**/*.html", "./static/app.js"],
  theme: {
    extend: {
      colors: {
        paper: tone("paper"), surface: tone("surface"), ink: tone("ink"),
        muted: tone("muted"), rule: tone("rule"), ledger: tone("ledger"),
        debit: tone("debit"), card: tone("card"), gain: tone("gain"), onaccent: tone("onaccent"),
      },
      fontFamily: {
        sans: ['"Public Sans"', "-apple-system", "BlinkMacSystemFont", '"Segoe UI"', "sans-serif"],
      },
    },
  },
  plugins: [],
};
