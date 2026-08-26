import { mount } from "@/mount";
import { fetchMountConfig } from "@/core/bootstrap/fetch-mount-config";
import { renderBootError } from "@/core/bootstrap/boot-error";
// oxlint-disable-next-line ssr-friendly/no-dom-globals-in-module-scope
const el = document.getElementById("root");
if (!el) {
    throw new Error("[sp] root element not found");
}
void (async () => {
    try {
        const config = await fetchMountConfig();
        await mount(config, el);
    }
    catch (err) {
        renderBootError(el, err);
    }
})();
