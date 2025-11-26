# Deployment Instructions

## Prerequisites
- Node.js installed
- Firebase account
- Vercel account
- Google Gemini API Key

## 1. Environment Variables
Create a `.env.local` file in the root directory with the following keys:

```env
NEXT_PUBLIC_FIREBASE_API_KEY=your_api_key
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=your_project_id.firebaseapp.com
NEXT_PUBLIC_FIREBASE_PROJECT_ID=your_project_id
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=your_project_id.appspot.com
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=your_sender_id
NEXT_PUBLIC_FIREBASE_APP_ID=your_app_id
GEMINI_API_KEY=your_gemini_api_key
```

## 2. Firebase Setup
1. Go to [Firebase Console](https://console.firebase.google.com/).
2. Create a new project.
3. Enable **Authentication** (Google & Email/Password).
4. Enable **Firestore Database** (Start in Test Mode or set rules).
5. Enable **Storage** (Start in Test Mode or set rules).
6. Copy the config values to your `.env.local`.

## 3. Run Locally
```bash
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000).

## 4. Deploy to Vercel
1. Install Vercel CLI: `npm i -g vercel`
2. Run `vercel` in the project root.
3. Follow the prompts.
4. Go to the Vercel Dashboard for your project.
5. Navigate to **Settings > Environment Variables**.
6. Add all the variables from `.env.local`.
7. Redeploy if necessary.

## 5. Firestore Rules (Basic Security)
```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if request.auth != null;
    }
  }
}
```

## 6. Storage Rules (Basic Security)
```
rules_version = '2';
service firebase.storage {
  match /b/{bucket}/o {
    match /{allPaths=**} {
      allow read, write: if request.auth != null;
    }
  }
}
```
