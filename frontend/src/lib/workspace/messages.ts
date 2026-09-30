/**
 * Messages (P7): governed objects between people. A message is a reference
 * (object id + version + card); opening it goes through the reader's own
 * permissions. Every action acts on the same object.
 */

import { wsGet, wsSend } from "./client";
import type { GovernedObject } from "./objects";
import type { Run } from "./runs";

export interface ShareCard {
  object_id: string;
  version: number;
  kind: string;
  title: string;
  name?: string;
  status: string;
  domain_id: string;
  period: string;
  owner_id: string;
  seeded?: boolean;
  executed?: boolean;
  scope_label?: string;
  components?: string[];
  author?: string;
  methods?: string[];
  methods_unavailable?: Record<string, string>;
  baseline?: string;
  chain?: string[];
  entities?: number;
  changes?: Record<string, string | null>;
  selected_change?: string | null;
  total_change?: string | null;
  top_components?: { id: string; label: string; value: string }[];
  limitations?: string[];
  membership_hash?: string;
  description?: string;
  items?: string[];
  method?: string;
  persona?: string;
  alert_type?: string;
  severity?: string;
  lens_name?: string;
  metric_id?: string;
  observed?: number | null;
  threshold?: number | null;
  comparison?: string;
  refresh?: string;
  attachments?: { object_id: string; kind: string; version: number }[];
}

export interface MessageItem {
  share_id: string;
  direction: "received" | "sent";
  from_id: string;
  to_id: string;
  object_id: string;
  version: number;
  kind: string;
  message: string;
  created_at: number;
  read_at: number | null;
  seeded: boolean;
  card: ShareCard;
}

export interface MessageAction {
  action: "open" | "run" | "rerun_latest" | "duplicate" | "save" | "compare" | "investigate" | "comment" | "open_thread" | "open_monitoring" | "whatif";
  label: string;
  href: string;
}

export interface MessageDetail {
  share: MessageItem;
  accessible: boolean;
  reason?: string;
  object?: GovernedObject;
  card?: ShareCard;
  latest_version?: number;
  newer_content?: boolean;
  actions: MessageAction[];
  comments: { comment_id: string; version: number; author_id: string; body: string; created_at: number }[];
  attachments?: ShareCard["attachments"];
}

export const readInbox = (box: "inbox" | "sent" | "all" = "inbox") =>
  wsGet<{ box: string; items: MessageItem[]; unread: number }>(`/messages?box=${box}`);

export const readMessage = (id: string) => wsGet<MessageDetail>(`/messages/${encodeURIComponent(id)}`);

export const sendObject = (objectId: string, to: string[], message = "", version?: number) =>
  wsSend<{ shared: { share_id: string }[]; object: ShareCard }>("/messages", { object_id: objectId, to, message, version });

const act = <T>(id: string, what: string, body: Record<string, unknown> = {}) =>
  wsSend<T>(`/messages/${encodeURIComponent(id)}/${what}`, body);

export const runFromMessage = (id: string, opts: { cohort_id?: string; latest?: boolean } = {}) => act<Run>(id, "run", opts);
export const duplicateFromMessage = (id: string) => act<GovernedObject>(id, "duplicate");
export const saveFromMessage = (id: string) => act<GovernedObject>(id, "save");
export const compareFromMessage = (id: string, withResultIds: string[]) =>
  act<GovernedObject>(id, "compare", { with_result_ids: withResultIds });
export const investigateFromMessage = (id: string) => act<{ thread_id: string }>(id, "investigate");
export const whatifFromMessage = (id: string) => act<GovernedObject>(id, "whatif");
export const commentOnMessage = (id: string, body: string) => act<{ comment_id: string }>(id, "comments", { body });

export const listMyResults = (domain: string) =>
  wsGet<{ results: (ShareCard & { created_at: number; mine: boolean })[] }>(`/whatif/results?domain=${domain}`);

/** Where a saved/duplicated object opens. */
export function hrefFor(obj: { kind: string; object_id: string }): string {
  switch (obj.kind) {
    case "scenario":
      return `/scenarios/${obj.object_id}`;
    case "scenario_result":
      return `/what-if/result/${obj.object_id}`;
    case "comparison":
      return `/what-if/compare/${obj.object_id}`;
    case "cohort":
      return `/what-if?cohort=${obj.object_id}`;
    case "run":
      return `/what-if?run=${obj.object_id}`;
    case "lens":
      return `/lenses/${obj.object_id}`;
    default:
      return `/messages`;
  }
}
