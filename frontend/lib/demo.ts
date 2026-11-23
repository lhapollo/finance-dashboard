/**
 * True in the demo copy of the app (fake data, http://localhost:3001): docker-compose.yml
 * sets NEXT_PUBLIC_DEMO for it. Used to hide what makes no sense on fake data, like
 * uploading a bank CSV.
 */
export const IS_DEMO = process.env.NEXT_PUBLIC_DEMO === "true";
