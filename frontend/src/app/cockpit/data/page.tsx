import { DataBooks } from "@/components/cockpit-v4/data-books";

export const metadata = {
  title: "Data · CreditProbe Cockpit",
};

export default function CockpitDataPage() {
  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-10">
      <DataBooks />
    </main>
  );
}
