import { createApp } from "./app.js";
import { config } from "./config.js";

createApp().listen(config.port, () => console.log(`api listening on :${config.port}`));
