import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
const root=path.resolve('examples/demo'); fs.mkdirSync(path.join(root,'.ldh'),{recursive:true});
const db=new DatabaseSync(path.join(root,'.ldh','demo.db'));
db.exec(`CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY,email TEXT); CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,customer_id INTEGER,amount REAL); DELETE FROM customers; DELETE FROM orders; INSERT INTO customers VALUES(1,'ada@example.com'),(2,'grace@example.com'); INSERT INTO orders VALUES(10,1,42.5),(11,1,20),(12,2,99);`);
console.log('Demo SQLite database ready.');
