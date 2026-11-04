# ApexRx — Customer Bases, Roles, and System Functions

## 1. Purpose of ApexRx

ApexRx is a medicine discovery and availability platform that connects people looking for medicines with pharmacies, and helps pharmacies discover and source medicines from suppliers.

The system supports two main connections:

1. **Patients → Pharmacies:** Patients search for medicines and discover pharmacies where those medicines are available.
2. **Pharmacies → Suppliers:** Pharmacies search for medicines from suppliers, compare supplier availability and prices, and coordinate orders.

The goal is to improve medicine availability and visibility without requiring pharmacies or suppliers to replace their existing systems.

---

## 2. Customer Base: Patients

### Role in ApexRx
Patients use ApexRx to find medicines and identify pharmacies where they may be able to obtain them.

### Main functions
- Search for a medicine by name.
- Discover pharmacies that report having the medicine available.
- Filter or compare pharmacy results by:
  - Availability
  - Price
  - Location or distance
- View a pharmacy's location and get directions.
- See an indication of availability, such as:
  - In stock
  - Low stock
  - Unavailable

### Important MVP decisions
- Patients do not need an account to search for medicines.
- Patients do not manage stock or place supplier orders.
- Patients see availability information; they do not need to see a pharmacy's exact stock quantity.
- The freshness of the availability information matters.

---

## 3. Customer Base: Pharmacies

### Role in ApexRx
Pharmacies use ApexRx both to make their medicines discoverable to patients and to find suppliers from whom they can source medicines.

### Main functions

#### A. Pharmacy registration and setup
- Register a pharmacy organization.
- Submit required documents for verification.
- Set up one or more pharmacy branches/locations.
- Have staff members access the organization using their own user accounts and assigned roles.

#### B. Medicine and stock management
- Find medicines in the shared ApexRx medicine catalogue.
- Manually record or update stock at a pharmacy location for the MVP.
- Set the pharmacy's selling price for a medicine.
- Publish medicine availability to patients.
- Keep stock and availability information updated.

#### C. Supplier discovery
- Search for medicines offered by suppliers.
- Discover suppliers based on product, price, availability, and location.
- View exact supplier stock quantities.
- Contact suppliers, for example through WhatsApp or another agreed communication channel.

#### D. Purchase orders
- Create a purchase order for a supplier.
- Specify the products and requested quantities.
- Select the pharmacy branch/location that will receive the order.
- Track the order's status.
- Receive the supplier's response, including confirmation or rejection and any confirmed price or quantity.

### Important MVP decisions
- Pharmacies manually manage stock in ApexRx for the MVP.
- ApexRx is not intended to replace a pharmacy's existing management system.
- Pharmacies can have multiple branches.
- Staff use individual accounts; they should not share a single organization login.
- Pharmacy selling prices are set by the pharmacy.
- Supplier exact stock quantities are visible to pharmacies, not patients.

---

## 4. Customer Base: Suppliers

### Role in ApexRx
Suppliers use ApexRx to make their products and stock discoverable to pharmacies and to receive and fulfil pharmacy purchase orders.

### Main functions

#### A. Supplier registration and setup
- Register a supplier organization.
- Submit required documents for verification.
- Set up one or more supplier warehouse/location records.
- Have staff access the organization using their own user accounts and assigned roles.

#### B. Medicine and stock management
- Find medicines in the shared ApexRx medicine catalogue.
- Manually record or update stock at supplier locations for the MVP.
- Set the supplier's selling price to pharmacies.
- Make product availability and stock information visible to pharmacies.

#### C. Purchase order management
- Receive purchase orders from pharmacies.
- Review the requested products and quantities.
- Accept or reject a purchase order.
- Confirm price and quantity before acceptance.
- Fulfil and update the order status.

### Important MVP decisions
- Suppliers manually manage stock in ApexRx for the MVP.
- Suppliers can have multiple warehouses/locations.
- Suppliers expose exact stock quantities to pharmacies.
- Partial fulfilment is not included in the MVP scope.

---

## 5. System Role: Administrators

Administrators are not a customer base. They operate and oversee the ApexRx platform.

### Main functions
- Review pharmacy and supplier registrations.
- Review submitted organization documents.
- Approve, reject, or otherwise manage organization access.
- Help ensure that only verified organizations can use the relevant pharmacy/supplier functions.

The exact document requirements and verification process still need to be confirmed.

---

## 6. How the Customer Bases Interact

### Patient → Pharmacy

A patient searches for a medicine in ApexRx.

ApexRx returns pharmacies reporting that medicine as available, along with relevant price and location information.

The patient can compare options and choose a pharmacy to visit.

### Pharmacy → Supplier

A pharmacy searches ApexRx for a medicine it needs to source.

ApexRx returns suppliers that offer the medicine, with relevant price, stock, and location information.

The pharmacy can contact a supplier or submit a purchase order. The supplier responds to the order and, if accepted, fulfils it.

---

## 7. Shared System Concepts

The following concepts are common to the customer workflows:

- **User:** An individual with their own login.
- **Organization:** A pharmacy or supplier business.
- **Membership:** The relationship between a user and an organization, including the user's role.
- **Location:** A pharmacy branch or supplier warehouse.
- **Medicine catalogue:** A shared catalogue of medicines/products used by both pharmacies and suppliers.
- **Stock:** The quantity of a product reported at a particular organization location.
- **Price:** The price set by a pharmacy for patients or by a supplier for pharmacies.
- **Purchase order:** A pharmacy's request to purchase products from a supplier.

These are business concepts to guide the data model. Their exact table structure and relationships will be decided in the database redesign.

---

## 8. MVP Scope Summary

| Customer base / role | What they use ApexRx for |
|---|---|
| Patients | Search for medicines and discover pharmacies with reported availability |
| Pharmacies | Publish availability and prices, find suppliers, and manage purchase orders |
| Suppliers | Publish stock and prices, receive and fulfil pharmacy orders |
| Administrators | Verify organizations and manage platform access |

**Core principle:** ApexRx connects medicine demand with reported availability and connects pharmacy procurement needs with supplier stock. It should enable these workflows without becoming a full pharmacy or supplier management/ERP system.
