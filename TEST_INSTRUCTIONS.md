# Vernis v3 - Full Functionality Test

**Tester:** antigravit
**Date:** 2026-01-27
**Devices:** afro (10.0.0.28), afroz (10.0.0.34)

---

## Instructions

Please test each feature below and mark the result:

- ✅ = Working
- ❌ = Not working (describe the issue)
- ⚠️ = Partially working (describe what's wrong)

After testing, please report back with your findings.

---

## 1. HOME PAGE (index.html)

### 1.1 Status Bar

- [ ] Status bar shows at bottom: "X Pinned • WiFi-Name [storage bar]"
- [ ] Storage bar is visible (small green/gray bar)
- [ ] Click status bar → expands to show storage details "💾 X GB free of Y GB (Z% available)"
- [ ] Screen Off button works
- [ ] Shutdown button shows confirmation dialog

### 1.2 Navigation

- [ ] Header shows: Home | Add Art | Library | Gallery | Settings
- [ ] All nav links work correctly

### 1.3 Cards

- [ ] QR code displays correctly
- [ ] Connect URL shows correct IP address
- [ ] All card buttons work (Start Gallery, Open Remote, Browse Library, Manage NFTs)

---

## 2. ADD ART PAGE (add.html)

### 2.1 Quick Add by CID

- [ ] "Quick Add by CID" section visible at top
- [ ] Enter this test CID: `Qmd84riUv6pCM1G3YiNqyJ8j4WvU1p6cH9q9cvRn9FhK3J`
- [ ] Enter name: "Test IPFS Folder"
- [ ] Click "Add to Gallery"
- [ ] Success message appears
- [ ] **Report any error message shown**

### 2.2 CSV Upload

- [ ] Create a test CSV file with this content:

```csv
contract_address,token_id,ipfs_cid,name,description
,,QmczM54SVFwQkwMfkmQUPfd8dHGoNjKu2FPQMStQxg42Nm,Test Image 1,A test NFT
,,bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi,Test Image 2,Another test
```

- [ ] Save as `test-collection.csv`
- [ ] Drag & drop or click to upload
- [ ] Enter collection name: "My Test Collection"
- [ ] Success message appears with item count
- [ ] **Report any error message shown**

### 2.3 Download Template

- [ ] Click "Download CSV Template" button
- [ ] CSV file downloads correctly

---

## 3. LIBRARY PAGE (library.html)

### 3.1 Display

- [ ] Collections load and display as cards
- [ ] Storage ring (donut chart) visible in toolbar showing disk usage
- [ ] Sort dropdown defaults to "Progress"
- [ ] Search box works

### 3.2 Collection Cards

- [ ] Each card shows: name, NFT count, description
- [ ] Progress bar at bottom of cards shows download status
- [ ] Green = fully downloaded & pinned
- [ ] Orange = downloaded but not pinned
- [ ] Blue = partially downloaded

### 3.3 Install & Pin

- [ ] Click "Install & Pin" on any collection
- [ ] Progress bar starts animating
- [ ] Download count updates
- [ ] **Report any error message shown**

### 3.4 Card Menu (3 dots)

- [ ] Click 3-dot menu on a card
- [ ] "View Info" shows collection details
- [ ] "Clear Downloaded Files" works
- [ ] "Remove Collection" works (with confirmation)

### 3.5 Add Collection Card

- [ ] "Add Collection" card visible (dashed border)
- [ ] Clicking it opens upload modal

### 3.6 Sync Button

- [ ] Click Sync button
- [ ] Shows syncing animation
- [ ] Completes without error

---

## 4. MANAGE PAGE (manage.html)

### 4.1 Display

- [ ] NFT grid loads with thumbnails
- [ ] Stats show: Total NFTs, In Carousel, Hidden, Selected

### 4.2 Selection

- [ ] Click NFT card to select (checkbox appears)
- [ ] "Select All" button works
- [ ] "Deselect All" button works
- [ ] "Invert Selection" button works

### 4.3 Actions

- [ ] "Hide Selected" works
- [ ] "Show Selected" works
- [ ] "Hide All" works
- [ ] "Show All" works
- [ ] "Delete Selected" shows confirmation

### 4.4 Filters & Sort

- [ ] Filter dropdown (All/In Carousel/Hidden) works
- [ ] Collection filter dropdown works
- [ ] Artist filter dropdown works
- [ ] Sort dropdown works
- [ ] Search box works

### 4.5 Carousels

- [ ] Save Current → prompts for name
- [ ] Load → loads saved carousel
- [ ] Download → downloads JSON file
- [ ] Import → imports JSON file

### 4.6 Button Spacing

- [ ] All buttons have proper spacing (not cramped)
- [ ] Select dropdowns not too wide

---

## 5. GALLERY PAGE (gallery.html)

### 5.1 Display

- [ ] Gallery loads and shows NFTs fullscreen
- [ ] Auto-advances to next image

### 5.2 Controls

- [ ] Hover/tap shows controls
- [ ] Previous/Next buttons work
- [ ] Pause/Play button works

### 5.3 Hue Toggle (if Hue connected)

- [ ] Hue button visible (only if Hue is connected)
- [ ] Toggle turns Hue sync on/off

---

## 6. SETTINGS PAGE (settings.html)

### 6.1 Theme Selection

- [ ] Theme dropdown shows options
- [ ] Select "XCOPY" theme
- [ ] Page updates with neon cyan/magenta colors, glitch effects
- [ ] Logo changes to "XCOPY"
- [ ] Select another theme → changes correctly

### 6.2 Display Settings

- [ ] Interval slider works
- [ ] Shuffle toggle works
- [ ] Orientation options work

### 6.3 Backup & Restore

- [ ] Tooltip visible under backup buttons: "Creates a snapshot of your library database..."
- [ ] "Create Backup" button works
- [ ] Progress bar shows during backup
- [ ] "Import Backup" button works

### 6.4 Storage Section

- [ ] Storage health shows disk usage
- [ ] External storage section visible (if drive connected)

### 6.5 IPFS Settings

- [ ] IPFS toggle works
- [ ] Auto-pin toggle works

### 6.6 Pi LED Toggle

- [ ] LED toggle visible
- [ ] Toggling turns Pi LED on/off

### 6.7 Sync Collections

- [ ] "Sync Collections" button works
- [ ] Shows arrow animation while syncing

---

## 7. VIRTUAL KEYBOARD (Touch devices)

- [ ] On text input, keyboard icon (⌨) appears
- [ ] Tapping keyboard icon opens on-screen keyboard
- [ ] Typing works correctly
- [ ] Shift/symbols modes work
- [ ] Backspace works
- [ ] Enter closes keyboard

---

## 8. RESPONSIVE DESIGN

### 8.1 Mobile/Tablet

- [ ] Navigation works on small screens
- [ ] Cards stack properly
- [ ] Buttons remain usable

### 8.2 Portrait Orientation

- [ ] Layout adjusts for vertical screens
- [ ] Content remains readable

---

## 9. ERROR HANDLING

Try these intentional errors and report responses:

### 9.1 Invalid CID

- [ ] Go to Add Art → Quick Add
- [ ] Enter CID: `invalid123`
- [ ] Expected: Error message "Invalid CID format"
- [ ] **Report actual result:**

### 9.2 Empty CSV

- [ ] Create empty CSV file
- [ ] Try to upload
- [ ] **Report actual result:**

---

## Test Report

### Summary

- Total tests: \_\_\_
- Passed: \_\_\_
- Failed: \_\_\_

### Issues Found

| Page | Feature | Expected | Actual | Severity |
| ---- | ------- | -------- | ------ | -------- |
|      |         |          |        |          |
|      |         |          |        |          |
|      |         |          |        |          |

### Additional Notes

---

**Please send this completed report back with your findings.**
