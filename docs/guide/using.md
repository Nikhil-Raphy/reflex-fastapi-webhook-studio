# Use the pages

Every page shows the app's version, such as `v1.2.0`, beside the app's name at the top.

## Make and open bins

On the home page, type a label if you want one and press **New bin**. The bin's page opens with its URL, a
**Copy URL** button, and when the bin expires. While the bin is empty, the page shows a curl command to copy.

The home page lists the bins made in this browser, or every bin when `WEBHOOK_STUDIO_BIN_LISTING` is `all`, with how
many requests each holds and when each expires. A bin expires `WEBHOOK_STUDIO_BIN_TTL_DAYS` days after its last
request (7 by default), and is then deleted with all it caught; the home page forgets it. To open a bin made
elsewhere, paste its id, its URL or its page address into the **Open a bin** box.

## Inspect requests

The list on the left shows the newest request first, with the method in a colour of its own. Click one to see it in
five tabs:

- **Overview:** the request id, time, method, path, query string, content type, body size, client address, HTTP
  version and the status sent back.
- **Headers:** every header in the order it reached the app. In Docker, Caddy changes some headers first; see
  [What to know](deploy.md#what-to-know). Headers that often hold secrets, such as `Authorization`,
  `Cookie` and names holding `token`, `secret`, `signature`, `api-key`, `password` or `session`, show as `••••` until
  you click them.
- **Query:** the raw query string, and each name and value in order.
- **Body:** JSON laid out with indents, form data as a table, other text as it came, and binary bodies as their size
  with a **Download** button. The page never renders a body as HTML.
- **Replay:** send the request again to another URL.

## Find requests

Pick a method above the list to show only requests with that method, or type in the search box to show only
requests whose method, path, query string, headers or first 4 KiB of body hold the text, in any case. The search
waits until you stop typing. A line under the boxes says how many requests match; **Clear filters** shows them all.

The list loads 50 requests at a time and loads the next 50 when you scroll near its end. A **Load older** button does
the same.

## Live updates

New requests and deletes show at once, in every tab that has the bin open. The dot at the top right shows **Live**
(green), **Connecting** (amber) or **Offline** (red). After a reconnect the page reloads the bin, so it misses
nothing. If someone deletes the bin, every open page says so.

## Delete, clear and export

- **Delete request** deletes the request on show.
- **Clear** deletes every request in the bin. The bin keeps its URL and reply settings.
- **Delete bin** deletes the bin with all it caught, and goes to the home page.
- **Export** downloads the bin and every request in it as one JSON file; see [the export format](api.md#export).

Each delete asks first. Each kind has its own **Don't ask again** box, which this browser remembers.

## Copy as curl

**Copy as curl** copies a command that sends the request on show to the bin again, with the same method, path,
query, headers and body bytes. Every value is quoted for the shell. A body that is not text goes through `base64`,
so its bytes survive.

## Choose the reply

**Reply settings** sets what the bin sends back: the status, the content type, extra headers, the body and a delay.
Leave **Custom body** off to send the usual `{"ok": true, "request_id": "…"}`. **Use default** puts everything back.
The rules are in [Set the reply](api.md#set-the-reply). The page shows each request before the delay ends.

## Replay a request

The **Replay** tab sends the request on show to a URL you type, with the same method, headers and body bytes. It
leaves out headers that belong to one connection, and `Host` and `Content-Length`. **Use original query string** adds
the request's query to the URL. The tab shows the status, the time taken, the headers and the first 64 KiB of the
body. Nothing is stored.

By default a replay may reach only public internet addresses. The app checks the address as the connection opens,
so it refuses this machine, private networks, link-local addresses such as cloud metadata, and names that point
there. Set `WEBHOOK_STUDIO_REPLAY_MODE=local` to replay to services on your own machine.
