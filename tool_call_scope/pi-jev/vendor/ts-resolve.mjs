/** Resolve pi-jev's extensionless relative imports (`./client`) to `.ts`.
 *
 * The vendored sources are byte-identical to the installed package -- asserted
 * by a test -- so nothing about the product's own code is edited to make it
 * run here. This hook exists only because Node refuses to strip types inside
 * node_modules, which is why the files are vendored at all. */
export async function resolve(specifier, context, next) {
  if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
    try { return await next(specifier + ".ts", context); } catch { /* fall through */ }
  }
  return next(specifier, context);
}
