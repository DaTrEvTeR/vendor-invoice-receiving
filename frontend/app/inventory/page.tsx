"use client";

import Link from "next/link";

import { ErrorBox } from "@/components/ErrorBox";
import { api } from "@/lib/api";
import { dateTime, text } from "@/lib/format";
import { useLoad } from "@/lib/useLoad";

export default function InventoryPage() {
  const products = useLoad(api.products);
  const movements = useLoad(api.stockMovements);
  const receipts = movements.data?.filter((movement) => movement.kind === "receipt");

  return (
    <>
      <h1>Inventory</h1>
      <p className="muted">
        On hand is always the sum of the stock ledger: opening stock from the catalog plus every receipt.
      </p>
      <ErrorBox error={products.error ?? movements.error} />

      <h2>Receipts</h2>
      {receipts && receipts.length === 0 && <p className="muted">Nothing received yet.</p>}
      {receipts && receipts.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>SKU</th>
              <th className="num">Quantity</th>
              <th className="num">Line amount</th>
              <th>Invoice</th>
              <th>PO</th>
            </tr>
          </thead>
          <tbody>
            {receipts.map((movement) => (
              <tr key={movement.id}>
                <td>{dateTime(movement.created_at)}</td>
                <td>{movement.sku}</td>
                <td className="num">{movement.quantity}</td>
                <td className="num">
                  {text(movement.total_cost)} {movement.currency}
                </td>
                <td>
                  {movement.invoice && (
                    <Link href={`/invoices/${movement.invoice.id}`}>{movement.invoice.source_filename}</Link>
                  )}
                </td>
                <td>{text(movement.po_number)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Stock by SKU</h2>
      {products.data && (
        <table>
          <thead>
            <tr>
              <th>SKU</th>
              <th>Name</th>
              <th>Category</th>
              <th>Unit</th>
              <th>Serialized</th>
              <th className="num">On hand</th>
              <th className="num">Default cost</th>
            </tr>
          </thead>
          <tbody>
            {products.data.map((product) => (
              <tr key={product.sku}>
                <td>{product.sku}</td>
                <td>{product.name}</td>
                <td>{product.category}</td>
                <td>{product.unit}</td>
                <td>{product.serialized ? "yes" : ""}</td>
                <td className="num">{product.on_hand}</td>
                <td className="num">{product.default_cost}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
