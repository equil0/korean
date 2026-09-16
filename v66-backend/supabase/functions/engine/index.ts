import handler from '../../../backend/index.ts';

declare const Deno: {
  serve(handler: (request: Request) => Promise<Response> | Response): void;
};

Deno.serve((request: Request) => handler.fetch(request));

